"""Автоматическая обработка заявки на стороне банка.

Шаги идемпотентны и возобновляемы: обработчик смотрит на текущий статус
и выполняет следующий шаг. Если воркер упал посреди обработки, задача
будет повторена и продолжит с того же места.

    SUBMITTED → VALIDATION → (NEEDS_INFO | ENRICHMENT)
    ENRICHMENT → (SCORING | NEEDS_INFO | MANUAL_REVIEW)
    SCORING → (APPROVED | COUNTER_OFFER | REJECTED | MANUAL_REVIEW)
    SIGNED → ISSUED   (задача DISBURSE)
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from ..config import get_settings
from ..domain.policy import decide
from ..domain.products import PRODUCTS
from ..domain.scoring import ScoringInput, score
from ..domain.statuses import Actor, Status
from ..domain.validation import completeness_check, revenue_discrepancy
from ..integrations.gateway import DataGateway, IntegrationUnavailable, NotFoundInSource, get_gateway
from ..models import Application, InfoRequest
from . import applications as svc

log = logging.getLogger("scc.pipeline")
SOURCE_TITLES = {"egrul": "ЕГРЮЛ/ЕГРИП", "fns": "ФНС «Прозрачный бизнес»", "bki": "Бюро кредитных историй"}


def _months_between(d: date, today: date) -> int:
    return (today.year - d.year) * 12 + (today.month - d.month) - (1 if today.day < d.day else 0)


def build_scoring_input(app: Application, today: date | None = None) -> ScoringInput:
    e = app.enrichment or {}
    egrul, fns, bki = e.get("egrul") or {}, e.get("fns") or {}, e.get("bki") or {}
    today = today or datetime.now(UTC).date()
    reg = egrul.get("registration_date")
    age = _months_between(date.fromisoformat(reg), today) if reg else 0

    official = fns.get("revenue") or {}
    years = sorted(official, reverse=True)
    off_last = official.get(years[0]) if years else None
    off_prev = official.get(years[1]) if len(years) > 1 else None
    # Консервативно: если клиент и ФНС расходятся — берём меньшее
    revenue_last = min(x for x in (app.revenue_last_year, off_last) if x) if (app.revenue_last_year or off_last) else 0
    revenue_prev = off_prev or app.revenue_prev_year

    obligations = bki.get("obligations") or []
    bki_payments = sum(o.get("monthly_payment", 0) for o in obligations)
    return ScoringInput(
        legal_status=egrul.get("status", "NOT_FOUND"),
        business_age_months=max(age, 0),
        okved=egrul.get("okved") or app.company.okved,
        revenue_last=int(revenue_last),
        revenue_prev=int(revenue_prev) if revenue_prev else None,
        existing_monthly_payments=max(bki_payments, app.monthly_debt_payments or 0),
        max_overdue_days_12m=max((o.get("max_overdue_days_12m", 0) for o in obligations), default=0),
        current_overdue_amount=sum(o.get("current_overdue", 0) for o in obligations),
        inquiries_30d=bki.get("inquiries_30d", 0),
        tax_arrears=fns.get("tax_arrears", 0),
        mass_address=bool(fns.get("mass_address")),
        director_disqualified=bool((egrul.get("director") or {}).get("disqualified")),
    )


class Pipeline:
    def __init__(self, db: Session, gateway: DataGateway | None = None,
                 step_delay: float | None = None, sleep: Callable[[float], None] = time.sleep):
        s = get_settings()
        self.db = db
        self.gw = gateway or get_gateway()
        self.delay = s.pipeline_step_delay_sec if step_delay is None else step_delay
        self.sleep = sleep
        self.auto_limit = s.auto_decision_limit

    def _commit_and_pause(self) -> None:
        self.db.commit()
        if self.delay:
            self.sleep(self.delay)

    # ---------- обработка заявки ----------

    def process(self, app_id: str) -> str:
        app = svc.get_app(self.db, app_id)
        for _ in range(10):  # защита от зацикливания
            st = Status(app.status)
            if st == Status.SUBMITTED:
                svc.transition(self.db, app, Status.VALIDATION, Actor.SYSTEM, None)
            elif st == Status.VALIDATION:
                self._validate(app)
            elif st == Status.ENRICHMENT:
                self._enrich(app)
            elif st == Status.SCORING:
                self._score(app)
            else:
                break
            self._commit_and_pause()
            self.db.refresh(app)
        return app.status

    def _validate(self, app: Application) -> None:
        issues = completeness_check(svc.to_data(app), PRODUCTS[app.product_code])
        if issues:
            items = [{"field": i.field, "code": i.code, "message": i.message} for i in issues]
            self.db.add(InfoRequest(application_id=app.id, requested_by_type="SYSTEM", items=items,
                                    message="Для рассмотрения заявки не хватает сведений."))
            svc.transition(self.db, app, Status.NEEDS_INFO, Actor.SYSTEM, None,
                           "Не хватает документов или сведений", {"items": items})
            return
        svc.transition(self.db, app, Status.ENRICHMENT, Actor.SYSTEM, None, "Данные заявки полные")

    def _enrich(self, app: Application) -> None:
        inn = app.company.inn
        enrichment: dict = {"fetched_at": datetime.now(UTC).isoformat(), "calls": []}
        for source in ("egrul", "fns", "bki"):
            try:
                data, info = getattr(self.gw, source)(inn)
                enrichment[source] = data
                enrichment["calls"].append({"source": source, "attempts": info.attempts, "latency_ms": info.latency_ms,
                                            "ok": True})
                svc.log_event(self.db, app, "INTEGRATION", Actor.SYSTEM, None,
                              f"Получены данные: {SOURCE_TITLES[source]}",
                              {"source": source, "attempts": info.attempts, "latency_ms": info.latency_ms})
            except NotFoundInSource:
                enrichment[source] = None
                enrichment["calls"].append({"source": source, "ok": True, "not_found": True})
                svc.log_event(self.db, app, "INTEGRATION", Actor.SYSTEM, None,
                              f"{SOURCE_TITLES[source]}: сведений о компании нет", {"source": source})
            except IntegrationUnavailable as e:
                enrichment["calls"].append({"source": source, "ok": False, "error": e.reason})
                app.enrichment = enrichment
                svc.log_event(self.db, app, "INTEGRATION", Actor.SYSTEM, None,
                              f"{SOURCE_TITLES[source]} не отвечает: {e.reason}", {"source": source},
                              visible_to_client=False)
                svc.transition(self.db, app, Status.MANUAL_REVIEW, Actor.SYSTEM, None,
                               "Внешний источник недоступен — заявка передана специалисту, чтобы не задерживать решение",
                               {"unavailable_source": source})
                return
        app.enrichment = enrichment

        egrul = enrichment.get("egrul") or {}
        if egrul.get("okved") and not app.company.okved:
            app.company.okved, app.company.okved_name = egrul["okved"], egrul.get("okved_name")

        fns_rev = (enrichment.get("fns") or {}).get("revenue") or {}
        official = fns_rev[max(fns_rev)] if fns_rev else None
        has_statements = any(d.doc_type == "financial_statements" for d in app.documents)
        if revenue_discrepancy(app.revenue_last_year, official) and not has_statements:
            items = [{"field": "documents.financial_statements", "code": "revenue_mismatch",
                      "message": "Загрузите бухгалтерскую отчётность за последний год"},
                     {"field": "revenue_last_year", "code": "revenue_mismatch",
                      "message": f"Проверьте выручку: по данным ФНС — {official:,} ₽".replace(",", " ")}]
            self.db.add(InfoRequest(application_id=app.id, requested_by_type="SYSTEM", items=items,
                                    message="Указанная выручка заметно выше данных ФНС. Подтвердите её отчётностью "
                                            "или исправьте сумму."))
            svc.transition(self.db, app, Status.NEEDS_INFO, Actor.SYSTEM, None,
                           "Выручка в заявке расходится с данными ФНС", {"items": items})
            return
        svc.transition(self.db, app, Status.SCORING, Actor.SYSTEM, None, "Сведения о компании собраны")

    def _score(self, app: Application) -> None:
        inp = build_scoring_input(app)
        result = score(inp)
        product = PRODUCTS[app.product_code]
        d = decide(product, app.amount, app.term_months, result, inp, auto_limit=self.auto_limit)
        app.scoring = {**result.to_dict(), "input": inp.__dict__}
        app.decision = d.to_dict()
        app.offer = d.offer.to_dict() if d.offer else None
        svc.transition(self.db, app, d.outcome, Actor.SYSTEM, None, d.client_explanation,
                       {"score": result.score, "grade": result.grade, "policy": d.policy_version})

    # ---------- выдача (смоделирована) ----------

    def disburse(self, app_id: str) -> str:
        app = svc.get_app(self.db, app_id)
        if app.status != Status.SIGNED.value:
            return app.status
        if self.delay:
            self.sleep(self.delay)
        svc.transition(self.db, app, Status.ISSUED, Actor.SYSTEM, None,
                       f"{app.offer['amount']:,} ₽ зачислены на расчётный счёт".replace(",", " "),
                       {"account": "40702810" + app.company.inn[:10].ljust(12, "0"), "simulated": True})
        self.db.commit()
        return app.status


def run_job(db: Session, kind: str, app_id: str, gateway: DataGateway | None = None,
            step_delay: float | None = None) -> str:
    p = Pipeline(db, gateway, step_delay)
    if kind == "PROCESS_APPLICATION":
        return p.process(app_id)
    if kind == "DISBURSE":
        return p.disburse(app_id)
    raise ValueError(f"Неизвестный тип задачи {kind}")
