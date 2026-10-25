"""Сервис заявок.

Все изменения статуса идут через transition(): проверка по машине
состояний + запись в журнал событий + (при необходимости) постановка
задачи в очередь — в одной транзакции.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.policy import make_offer
from ..domain.products import DOCUMENTS, PRODUCTS, PURPOSES, required_documents
from ..domain.state_machine import TransitionError, check_transition
from ..domain.statuses import STATUS_INFO, Actor, Status
from ..domain.validation import ApplicationData, sanity_check, validate_for_submit
from ..errors import Conflict, NotFound, ValidationFailed
from ..models import Application, ApplicationEvent, Document, InfoRequest, Job, User

EDITABLE_FIELDS = ("product_code", "purpose", "purpose_comment", "amount", "term_months", "revenue_last_year",
                   "revenue_prev_year", "monthly_debt_payments", "collateral_type", "collateral_value")
ALLOWED_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png", "text/csv", "text/plain",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         "application/vnd.ms-excel", "application/octet-stream"}


def now() -> datetime:
    return datetime.now(UTC)


# ---------- журнал и очередь ----------

def log_event(db: Session, app: Application, kind: str, actor: Actor, actor_id: int | None, message: str,
              payload: dict | None = None, from_status: str | None = None, to_status: str | None = None,
              visible_to_client: bool = True) -> ApplicationEvent:
    ev = ApplicationEvent(application_id=app.id, kind=kind, actor_type=actor.value, actor_id=actor_id,
                          message=message, payload=payload, from_status=from_status, to_status=to_status,
                          visible_to_client=visible_to_client)
    db.add(ev)
    return ev


def enqueue(db: Session, app: Application, kind: str, delay_sec: float = 0) -> Job:
    job = Job(kind=kind, application_id=app.id, run_after=now() + timedelta(seconds=delay_sec))
    db.add(job)
    return job


def transition(db: Session, app: Application, target: Status, actor: Actor, actor_id: int | None,
               message: str | None = None, payload: dict | None = None) -> None:
    current = Status(app.status)
    try:
        check_transition(current, target, actor)
    except TransitionError as e:
        raise Conflict(str(e), code="invalid_transition") from e
    app.status = target.value
    ts = now()
    if target == Status.SUBMITTED and app.submitted_at is None:
        app.submitted_at = ts
    if target in (Status.APPROVED, Status.COUNTER_OFFER, Status.REJECTED):
        app.decided_at = ts
    if target == Status.ISSUED:
        app.issued_at = ts
    log_event(db, app, "STATUS", actor, actor_id, message or STATUS_INFO[target].title, payload,
              from_status=current.value, to_status=target.value)


# ---------- доступ ----------

def get_app(db: Session, app_id: str) -> Application:
    app = db.get(Application, app_id)
    if app is None:
        raise NotFound("Заявка не найдена")
    return app


def get_for_client(db: Session, user: User, app_id: str) -> Application:
    app = db.get(Application, app_id)
    # Чужая заявка неотличима от несуществующей — не раскрываем факт её наличия
    if app is None or app.company_id != user.company_id:
        raise NotFound("Заявка не найдена")
    return app


def list_for_client(db: Session, user: User) -> list[Application]:
    return list(db.scalars(select(Application).where(Application.company_id == user.company_id)
                           .order_by(Application.created_at.desc())))


def to_data(app: Application) -> ApplicationData:
    return ApplicationData(
        product_code=app.product_code, amount=app.amount, term_months=app.term_months, purpose=app.purpose,
        revenue_last_year=app.revenue_last_year, revenue_prev_year=app.revenue_prev_year,
        monthly_debt_payments=app.monthly_debt_payments, collateral_type=app.collateral_type,
        collateral_value=app.collateral_value, documents={d.doc_type for d in app.documents},
    )


# ---------- клиентские действия ----------

def _new_number() -> str:
    return f"SCC-{now():%y%m%d}-{secrets.token_hex(3).upper()}"


def _check_sanity(app: Application) -> None:
    """Опечатки в цифрах показываем сразу, на том шаге, где их ввели."""
    issues = sanity_check(to_data(app))
    if issues:
        raise ValidationFailed("Проверьте цифры",
                               [{"field": i.field, "code": i.code, "message": i.message} for i in issues])


def create_draft(db: Session, user: User, fields: dict, idempotency_key: str | None) -> Application:
    if idempotency_key:
        existing = db.scalar(select(Application).where(Application.idempotency_key == idempotency_key))
        if existing:
            if existing.company_id != user.company_id:
                raise Conflict("Ключ идемпотентности уже использован")
            return existing
    if fields.get("product_code") not in PRODUCTS:
        raise ValidationFailed("Неизвестный продукт", [{"field": "product_code", "message": "Выберите продукт"}])
    if fields.get("purpose") and fields["purpose"] not in PURPOSES:
        raise ValidationFailed("Неизвестная цель", [{"field": "purpose", "message": "Выберите цель"}])
    app = Application(number=_new_number(), company_id=user.company_id, applicant_id=user.id,
                      status=Status.DRAFT.value, idempotency_key=idempotency_key)
    for k in EDITABLE_FIELDS:
        if k in fields:
            setattr(app, k, fields[k])
    _check_sanity(app)
    db.add(app)
    db.flush()
    log_event(db, app, "STATUS", Actor.CLIENT, user.id, "Черновик заявки создан", to_status=Status.DRAFT.value)
    return app


def update_draft(db: Session, user: User, app: Application, fields: dict, expected_version: int | None) -> Application:
    if app.status != Status.DRAFT.value:
        raise Conflict("Изменять можно только черновик", code="not_editable")
    if expected_version is not None and expected_version != app.version:
        raise Conflict("Заявка изменена в другой вкладке. Обновите страницу", code="version_mismatch")
    if "product_code" in fields and fields["product_code"] not in PRODUCTS:
        raise ValidationFailed("Неизвестный продукт", [{"field": "product_code", "message": "Выберите продукт"}])
    for k in EDITABLE_FIELDS:
        if k in fields:
            setattr(app, k, fields[k])
    _check_sanity(app)
    return app


def submit(db: Session, user: User, app: Application) -> Application:
    if app.status != Status.DRAFT.value:
        # Повторная отправка (двойной клик, ретрай сети) — идемпотентна
        if app.status != Status.CANCELLED.value:
            return app
    product = PRODUCTS[app.product_code]
    issues = validate_for_submit(to_data(app), product)
    if issues:
        raise ValidationFailed("Проверьте поля заявки",
                               [{"field": i.field, "code": i.code, "message": i.message} for i in issues])
    transition(db, app, Status.SUBMITTED, Actor.CLIENT, user.id, "Заявка отправлена в банк")
    enqueue(db, app, "PROCESS_APPLICATION")
    return app


def add_document(db: Session, user: User, app: Application, doc_type: str, filename: str,
                 content_type: str, content: bytes, max_bytes: int) -> Document:
    if app.status not in (Status.DRAFT.value, Status.NEEDS_INFO.value, Status.MANUAL_REVIEW.value):
        raise Conflict("Сейчас документы добавить нельзя: заявка уже на следующем этапе", code="not_editable")
    if doc_type not in DOCUMENTS:
        raise ValidationFailed("Неизвестный тип документа", [{"field": "doc_type", "message": "Выберите тип"}])
    if not content:
        raise ValidationFailed("Файл пустой", [{"field": "file", "message": "Выберите непустой файл"}])
    if len(content) > max_bytes:
        raise ValidationFailed("Файл слишком большой",
                               [{"field": "file", "message": f"Максимум {max_bytes // 1024 // 1024} МБ"}])
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationFailed("Формат не поддерживается",
                               [{"field": "file", "message": "Загрузите PDF, JPG, PNG, CSV или XLSX"}])
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ()")[:200] or "document"
    doc = Document(application_id=app.id, doc_type=doc_type, filename=safe_name, content_type=content_type,
                   size=len(content), sha256=hashlib.sha256(content).hexdigest(), content=content,
                   uploaded_by=user.id)
    db.add(doc)
    app.documents.append(doc)
    log_event(db, app, "DOCUMENT", Actor.CLIENT, user.id, f"Загружен документ: {DOCUMENTS[doc_type]}",
              {"doc_type": doc_type, "filename": safe_name, "size": len(content)})
    return doc


def delete_document(db: Session, user: User, app: Application, doc_id: int) -> None:
    """Клиент убирает ошибочно загруженный файл. Пока банк не начал рассмотрение — в черновике и при дозапросе.
    Сам файл удаляется, а запись в журнале остаётся: кто, когда и какой документ убрал."""
    doc = next((d for d in app.documents if d.id == doc_id), None)
    if doc is None:
        raise NotFound("Документ не найден")
    if app.status not in (Status.DRAFT.value, Status.NEEDS_INFO.value):
        raise Conflict("Удалить документ нельзя: банк уже рассматривает заявку", code="not_editable")
    app.documents.remove(doc)
    db.delete(doc)
    log_event(db, app, "DOCUMENT", Actor.CLIENT, user.id, f"Удалён документ: {DOCUMENTS.get(doc.doc_type, doc.doc_type)}",
              {"doc_type": doc.doc_type, "filename": doc.filename})


def open_info_request(db: Session, app: Application) -> InfoRequest | None:
    return db.scalar(select(InfoRequest).where(InfoRequest.application_id == app.id, InfoRequest.status == "OPEN")
                     .order_by(InfoRequest.id.desc()))


def answer_info_request(db: Session, user: User, app: Application, response_text: str | None,
                        fields: dict) -> Application:
    if app.status != Status.NEEDS_INFO.value:
        raise Conflict("Банк сейчас ничего не запрашивал по этой заявке", code="not_needed")
    # Клиент может поправить финансовые поля в ответ на запрос
    for k in ("revenue_last_year", "revenue_prev_year", "monthly_debt_payments", "collateral_value"):
        if fields.get(k) is not None:
            setattr(app, k, fields[k])
    _check_sanity(app)
    req = open_info_request(db, app)
    if req:
        req.status, req.response_text, req.answered_at = "ANSWERED", response_text, now()
    transition(db, app, Status.SUBMITTED, Actor.CLIENT, user.id, "Клиент дополнил заявку",
               {"response": response_text} if response_text else None)
    enqueue(db, app, "PROCESS_APPLICATION")
    return app


def accept_offer(db: Session, user: User, app: Application) -> Application:
    if not app.offer:
        raise Conflict("По заявке нет предложения", code="no_offer")
    app.contract_number = app.contract_number or f"КД-{now():%y%m}-{secrets.token_hex(3).upper()}"
    transition(db, app, Status.OFFER_ACCEPTED, Actor.CLIENT, user.id,
               "Клиент принял условия, договор сформирован", {"offer": app.offer})
    return app


def sign(db: Session, user: User, app: Application, confirmation_inn: str) -> Application:
    if confirmation_inn.strip() != app.company.inn:
        raise ValidationFailed("ИНН не совпадает",
                               [{"field": "confirmation_inn", "message": "Введите ИНН компании, чтобы подписать договор"}])
    transition(db, app, Status.SIGNED, Actor.CLIENT, user.id,
               "Договор подписан простой электронной подписью (смоделировано)",
               {"contract_number": app.contract_number, "signed_by": user.full_name,
                "signature_hash": hashlib.sha256(f"{app.id}:{user.id}:{app.offer}".encode()).hexdigest()[:16]})
    enqueue(db, app, "DISBURSE", delay_sec=0)
    return app


def cancel(db: Session, user: User, app: Application, reason: str | None) -> Application:
    transition(db, app, Status.CANCELLED, Actor.CLIENT, user.id, "Заявка отменена клиентом",
               {"reason": reason} if reason else None)
    return app


# ---------- действия аналитика ----------

def assign(db: Session, analyst: User, app: Application) -> Application:
    if app.analyst_id and app.analyst_id != analyst.id:
        raise Conflict("Заявку уже взял в работу другой аналитик", code="already_assigned")
    app.analyst_id = analyst.id
    log_event(db, app, "COMMENT", Actor.ANALYST, analyst.id, f"Заявку взял в работу: {analyst.full_name}",
              visible_to_client=False)
    return app


def analyst_decide(db: Session, analyst: User, app: Application, outcome: Status, comment: str,
                   amount: int | None, term: int | None, rate: float | None) -> Application:
    if app.status != Status.MANUAL_REVIEW.value:
        raise Conflict("Решение аналитика принимается только на этапе ручного рассмотрения", code="invalid_state")
    if app.analyst_id is None:
        app.analyst_id = analyst.id
    elif app.analyst_id != analyst.id:
        raise Conflict("Заявку ведёт другой аналитик", code="already_assigned")
    product = PRODUCTS[app.product_code]
    decision = dict(app.decision or {})
    decision["manual"] = {"analyst_id": analyst.id, "analyst": analyst.full_name, "comment": comment,
                          "outcome": outcome.value, "at": now().isoformat()}
    if outcome in (Status.APPROVED, Status.COUNTER_OFFER):
        amount = amount or app.amount
        term = term or app.term_months
        rate = rate or (app.decision or {}).get("limits", {}).get("rate") or product.base_rate
        if not (product.min_amount <= amount <= product.max_amount and product.min_term <= term <= product.max_term):
            raise ValidationFailed("Условия вне параметров продукта",
                                   [{"field": "amount", "message": "Проверьте сумму и срок"}])
        if outcome == Status.APPROVED and (amount != app.amount or term != app.term_months):
            outcome = Status.COUNTER_OFFER  # условия отличаются от запрошенных — это встречное предложение
        app.offer = make_offer(amount, term, rate).to_dict()
        decision["client_explanation"] = comment
    else:
        app.offer = None
        decision["client_explanation"] = comment
    decision["outcome"] = outcome.value
    app.decision = decision
    transition(db, app, outcome, Actor.ANALYST, analyst.id, f"Решение кредитного специалиста: {STATUS_INFO[outcome].title}",
               {"comment": comment, "offer": app.offer})
    return app


def analyst_request_info(db: Session, analyst: User, app: Application, message: str, docs: list[str]) -> Application:
    items = [{"field": f"documents.{d}", "code": "missing_document", "message": f"Загрузите: {DOCUMENTS[d]}"}
             for d in docs if d in DOCUMENTS]
    db.add(InfoRequest(application_id=app.id, requested_by_type="ANALYST", requested_by_id=analyst.id,
                       message=message, items=items))
    transition(db, app, Status.NEEDS_INFO, Actor.ANALYST, analyst.id, "Специалист запросил дополнительные сведения",
               {"message": message, "items": items})
    return app


def required_docs_for(app: Application) -> list[dict]:
    if not app.product_code or app.product_code not in PRODUCTS:
        return []
    have = {d.doc_type for d in app.documents}
    return [{"code": d, "title": DOCUMENTS[d], "uploaded": d in have}
            for d in required_documents(PRODUCTS[app.product_code], app.amount or 0)]