from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..domain.products import PRODUCTS
from ..domain.statuses import STAGES, STATUS_INFO, Status
from ..models import Application, User
from ..schemas import ApplicationOut, DocumentOut, InfoRequestOut, QueueItem, StatusView
from ..services import applications as svc

CLIENT_ACTIONS: dict[Status, list[str]] = {
    Status.DRAFT: ["edit", "upload", "submit", "cancel"],
    Status.NEEDS_INFO: ["upload", "answer", "cancel"],
    Status.MANUAL_REVIEW: ["upload", "cancel"],
    Status.APPROVED: ["accept", "cancel"],
    Status.COUNTER_OFFER: ["accept", "cancel"],
    Status.OFFER_ACCEPTED: ["sign", "cancel"],
}
ANALYST_ACTIONS: dict[Status, list[str]] = {
    Status.MANUAL_REVIEW: ["assign", "decide", "request_info"],
}


def status_view(app: Application, role: str) -> StatusView:
    st = Status(app.status)
    info = STATUS_INFO[st]
    actions = (CLIENT_ACTIONS if role == "CLIENT" else ANALYST_ACTIONS).get(st, [])
    return StatusView(code=st.value, title=info.title, now=info.now, next_step=info.next_step,
                      waiting_for=info.waiting_for, stage=info.stage, stages=list(STAGES), allowed_actions=actions)


def client_decision(app: Application) -> dict | None:
    """Клиенту — решение и объяснение, без внутренних лимитов банка."""
    d = app.decision
    if not d or app.status in (Status.MANUAL_REVIEW.value, Status.SCORING.value):
        return None
    return {"outcome": d.get("outcome"), "client_explanation": d.get("client_explanation"),
            "decided_by": "specialist" if d.get("manual") else "auto"}


def client_score(app: Application) -> dict | None:
    s = app.scoring
    if not s or app.status in (Status.MANUAL_REVIEW.value, Status.SCORING.value):
        return None
    return {"grade": s["grade"], "factors": [{"title": f["title"], "impact": f["impact"], "text": f["client_text"]}
                                            for f in s["factors"]],
            "stop_factors": [{"title": x["title"], "text": x["client_text"]} for x in s.get("stop_factors", [])]}


def application_out(db: Session, app: Application, role: str = "CLIENT") -> ApplicationOut:
    req = svc.open_info_request(db, app) if app.status == Status.NEEDS_INFO.value else None
    return ApplicationOut(
        id=app.id, number=app.number, product_code=app.product_code,
        product_name=PRODUCTS[app.product_code].name, purpose=app.purpose, purpose_comment=app.purpose_comment,
        amount=app.amount, term_months=app.term_months, revenue_last_year=app.revenue_last_year,
        revenue_prev_year=app.revenue_prev_year, monthly_debt_payments=app.monthly_debt_payments,
        collateral_type=app.collateral_type, collateral_value=app.collateral_value,
        status=status_view(app, role), version=app.version, offer=app.offer,
        decision=client_decision(app) if role == "CLIENT" else app.decision,
        score=client_score(app) if role == "CLIENT" else app.scoring,
        contract_number=app.contract_number, required_documents=svc.required_docs_for(app),
        documents=[DocumentOut.model_validate(d) for d in app.documents],
        info_request=InfoRequestOut.model_validate(req) if req else None,
        created_at=app.created_at, updated_at=app.updated_at, submitted_at=app.submitted_at,
        decided_at=app.decided_at, issued_at=app.issued_at,
    )


def queue_item(app: Application, analysts: dict[int, User]) -> QueueItem:
    waiting = None
    if app.submitted_at:
        sub = app.submitted_at if app.submitted_at.tzinfo else app.submitted_at.replace(tzinfo=UTC)
        waiting = int((datetime.now(UTC) - sub).total_seconds() // 60)
    s = app.scoring or {}
    d = app.decision or {}
    analyst = analysts.get(app.analyst_id) if app.analyst_id else None
    return QueueItem(
        id=app.id, number=app.number, company_name=app.company.name, company_inn=app.company.inn,
        product_name=PRODUCTS[app.product_code].name, amount=app.amount, term_months=app.term_months,
        status=app.status, status_title=STATUS_INFO[Status(app.status)].title, grade=s.get("grade"),
        score=s.get("score"), analyst_id=app.analyst_id, analyst_name=analyst.full_name if analyst else None,
        submitted_at=app.submitted_at, waiting_minutes=waiting, reasons=d.get("reasons", [])[:3],
    )
