from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..domain import policy, scoring
from ..domain.products import PRODUCTS
from ..domain.state_machine import to_mermaid
from ..domain.statuses import STATUS_INFO, Status
from ..models import Application, ApplicationEvent, Job, User
from ..schemas import (AnalystApplicationOut, AnalystDecisionIn, AnalystInfoRequestIn, AuditEventOut, CompanyOut,
                       EventOut, QueueItem)
from ..security import ROLE_ANALYST, ROLE_RISK, require_roles
from ..services import applications as svc
from ..services.assistant import analyst_summary
from .common import commit
from .serializers import application_out, queue_item

analyst = APIRouter(prefix="/api/analyst", tags=["analyst"])
admin = APIRouter(prefix="/api/admin", tags=["admin"])
bank_staff = require_roles(ROLE_ANALYST, ROLE_RISK)
analyst_only = require_roles(ROLE_ANALYST)
risk_only = require_roles(ROLE_RISK, ROLE_ANALYST)


def _analysts(db: Session) -> dict[int, User]:
    return {u.id: u for u in db.scalars(select(User).where(User.role.in_([ROLE_ANALYST, ROLE_RISK])))}


@analyst.get("/queue", response_model=list[QueueItem], summary="Очередь заявок")
def queue(scope: str = Query("manual", pattern="^(manual|active|all)$"), db: Session = Depends(get_db),
          _: User = Depends(bank_staff)):
    q = select(Application).where(Application.status != Status.DRAFT.value)
    if scope == "manual":
        q = q.where(Application.status == Status.MANUAL_REVIEW.value)
    elif scope == "active":
        q = q.where(Application.status.notin_([Status.REJECTED.value, Status.ISSUED.value, Status.CANCELLED.value]))
    apps = list(db.scalars(q.order_by(Application.submitted_at.asc().nullslast()).limit(200)))
    analysts = _analysts(db)
    return [queue_item(a, analysts) for a in apps]


@analyst.get("/applications/{app_id}", response_model=AnalystApplicationOut, summary="Полная карточка для аналитика")
def card(app_id: str, db: Session = Depends(get_db), _: User = Depends(bank_staff)):
    app = svc.get_app(db, app_id)
    applicant = db.get(User, app.applicant_id)
    events = list(db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == app.id)
                             .order_by(ApplicationEvent.id)))
    return AnalystApplicationOut(
        application=application_out(db, app, "ANALYST"), company=CompanyOut.model_validate(app.company),
        applicant={"full_name": applicant.full_name, "position": applicant.position, "email": applicant.email},
        enrichment=app.enrichment, scoring=app.scoring, decision=app.decision,
        summary=analyst_summary(app.scoring, app.decision),
        events=[EventOut.model_validate(e) for e in events], analyst_id=app.analyst_id,
    )


@analyst.post("/applications/{app_id}/assign", summary="Взять заявку в работу")
def assign(app_id: str, db: Session = Depends(get_db), user: User = Depends(analyst_only)):
    app = svc.get_app(db, app_id)
    svc.assign(db, user, app)
    commit(db)
    return {"ok": True, "analyst_id": user.id}


@analyst.post("/applications/{app_id}/decision", summary="Решение по заявке на ручном рассмотрении")
def decision(app_id: str, body: AnalystDecisionIn, db: Session = Depends(get_db), user: User = Depends(analyst_only)):
    app = svc.get_app(db, app_id)
    svc.analyst_decide(db, user, app, Status(body.outcome), body.comment, body.amount, body.term_months, body.rate)
    commit(db)
    return {"ok": True, "status": app.status}


@analyst.post("/applications/{app_id}/request-info", summary="Запросить у клиента сведения или документы")
def request_info(app_id: str, body: AnalystInfoRequestIn, db: Session = Depends(get_db),
                 user: User = Depends(analyst_only)):
    app = svc.get_app(db, app_id)
    if app.status != Status.MANUAL_REVIEW.value:
        from ..errors import Conflict
        raise Conflict("Запросить сведения можно на этапе ручного рассмотрения", code="invalid_state")
    svc.analyst_request_info(db, user, app, body.message, body.documents)
    commit(db)
    return {"ok": True, "status": app.status}


@analyst.get("/stats", summary="Показатели конвейера")
def stats(db: Session = Depends(get_db), _: User = Depends(bank_staff)):
    by_status = dict(db.execute(select(Application.status, func.count()).group_by(Application.status)).all())
    decided = [s for s in (Status.APPROVED, Status.COUNTER_OFFER, Status.REJECTED, Status.OFFER_ACCEPTED,
                           Status.SIGNED, Status.ISSUED)]
    total_decided = sum(by_status.get(s.value, 0) for s in decided)
    manual_events = db.scalar(select(func.count()).select_from(ApplicationEvent)
                              .where(ApplicationEvent.to_status == Status.MANUAL_REVIEW.value)) or 0
    auto_decisions = db.scalar(select(func.count()).select_from(ApplicationEvent)
                               .where(ApplicationEvent.from_status == Status.SCORING.value,
                                      ApplicationEvent.to_status != Status.MANUAL_REVIEW.value)) or 0
    return {
        "by_status": {k: {"count": v, "title": STATUS_INFO[Status(k)].title} for k, v in by_status.items()},
        "decided_total": total_decided,
        "auto_decisions": auto_decisions,
        "manual_reviews": manual_events,
        "auto_share": round(auto_decisions / (auto_decisions + manual_events), 2) if (auto_decisions + manual_events) else None,
    }


# ---------- администрирование и аудит ----------

@admin.get("/audit", response_model=list[AuditEventOut], summary="Журнал событий (аудит)")
def audit(application_id: str | None = None, hidden_only: bool = Query(False, description="Только события, скрытые от клиента"),
          limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), _: User = Depends(risk_only)):
    q = select(ApplicationEvent).order_by(ApplicationEvent.id.desc()).limit(limit)
    if application_id:
        q = q.where(ApplicationEvent.application_id == application_id)
    if hidden_only:
        q = q.where(ApplicationEvent.visible_to_client.is_(False))
    events = list(db.scalars(q))
    apps = {a.id: a for a in db.scalars(select(Application).where(Application.id.in_({e.application_id for e in events})))}
    actor_ids = {e.actor_id for e in events if e.actor_id}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(actor_ids)))} if actor_ids else {}
    return [AuditEventOut(
        id=e.id, kind=e.kind, from_status=e.from_status, to_status=e.to_status, actor_type=e.actor_type,
        message=e.message, payload=e.payload, created_at=e.created_at, application_id=e.application_id,
        application_number=apps[e.application_id].number, company_name=apps[e.application_id].company.name,
        actor_name=users[e.actor_id].full_name if e.actor_id in users else None,
        visible_to_client=e.visible_to_client) for e in events]


@admin.get("/jobs", summary="Состояние очереди задач")
def jobs(db: Session = Depends(get_db), _: User = Depends(risk_only)):
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    failed = [{"id": j.id, "kind": j.kind, "application_id": j.application_id, "attempts": j.attempts,
               "error": j.last_error} for j in db.scalars(select(Job).where(Job.status == "FAILED").limit(20))]
    return {"counts": counts, "failed": failed}


@admin.get("/policy", summary="Действующая кредитная политика и скоринговая карта")
def get_policy(_: User = Depends(risk_only)):
    return {
        "policy_version": policy.POLICY_VERSION, "scorecard_version": scoring.SCORECARD_VERSION,
        "base_score": scoring.BASE_SCORE,
        "grades": [{"min_score": lo, "grade": g, "pd": pd} for lo, g, pd in scoring.GRADES],
        # Порог берётся из настроек — тот же, что использует конвейер (AUTO_DECISION_LIMIT)
        "auto_decision_limit": get_settings().auto_decision_limit, "min_dscr": policy.MIN_DSCR,
        "counter_min_share": policy.COUNTER_MIN_SHARE,
        "grade_rate_premium": policy.GRADE_RATE_PREMIUM, "grade_limit_multiplier": policy.GRADE_LIMIT_MULT,
        "products": {c: {"name": p.name, "base_rate": p.base_rate, "revenue_share": p.revenue_share,
                         "min_amount": p.min_amount, "max_amount": p.max_amount, "min_term": p.min_term,
                         "max_term": p.max_term} for c, p in PRODUCTS.items()},
        "industry_risk": {k: {"risk": r, "margin": m} for k, (r, m) in scoring.INDUSTRY_RISK.items()},
        "state_diagram_mermaid": to_mermaid(),
    }


health = APIRouter(tags=["health"])


@health.get("/health/live", summary="Liveness")
def live():
    return {"status": "ok"}


@health.get("/health/ready", summary="Readiness: доступность БД и очереди")
def ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    border = datetime.now(UTC) - timedelta(minutes=5)
    lagging = db.scalar(select(func.count()).select_from(Job).where(Job.status == "PENDING", Job.run_after < border)) or 0
    return {"status": "ok", "db": "ok", "jobs_lagging": lagging}


@admin.get("/integrations/chaos", summary="Текущий режим симуляции сбоев внешних источников")
def get_chaos(_: User = Depends(risk_only)):
    import httpx

    from ..config import get_settings
    try:
        return httpx.get(get_settings().integrations_url + "/_admin/chaos", timeout=3).json()
    except httpx.HTTPError as e:
        from ..errors import AppError
        raise AppError("Симулятор внешних источников недоступен", code="mocks_unavailable") from e


@admin.post("/integrations/chaos", summary="Включить/выключить сбои внешних источников (для демонстрации)")
def set_chaos(body: dict, _: User = Depends(risk_only)):
    import httpx

    from ..config import get_settings
    payload = {"fail_rate": float(body.get("fail_rate", 0)), "latency_ms": int(body.get("latency_ms", 0)),
               "sources": body.get("sources") or ["egrul", "fns", "bki"]}
    try:
        return httpx.post(get_settings().integrations_url + "/_admin/chaos", json=payload, timeout=3).json()
    except httpx.HTTPError as e:
        from ..errors import AppError
        raise AppError("Симулятор внешних источников недоступен", code="mocks_unavailable") from e