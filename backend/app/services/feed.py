from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.feed import Profile, rank_tips
from ..domain.policy import GRADE_LIMIT_MULT
from ..domain.products import PRODUCTS
from ..domain.statuses import STATUS_INFO, TERMINAL, Status
from ..models import Application, ApplicationEvent, User
from .applications import list_for_client

ACTION_STATUSES = {
    Status.DRAFT: ("Завершите заявку", "Черновик ещё не отправлен в банк."),
    Status.NEEDS_INFO: ("Банк ждёт уточнений", "Ответьте на запрос, чтобы банк продолжил рассмотрение."),
    Status.APPROVED: ("Заявка одобрена", "Примите условия, чтобы перейти к подписанию."),
    Status.COUNTER_OFFER: ("Банк предлагает другие условия", "Посмотрите встречное предложение."),
    Status.OFFER_ACCEPTED: ("Подпишите договор", "Договор готов — осталось подписать его в кабинете."),
}


@lru_cache
def _tips() -> list[dict]:
    return json.loads((Path(__file__).parent.parent / "data" / "tips.json").read_text(encoding="utf-8"))


def _money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₽"


def build_feed(db: Session, user: User) -> dict:
    apps = list_for_client(db, user)
    company = user.company
    items: list[dict] = []

    for a in apps:
        st = Status(a.status)
        if st in ACTION_STATUSES:
            title, body = ACTION_STATUSES[st]
            items.append({"id": f"act-{a.id}", "kind": "action", "title": title,
                          "body": f"{body} Заявка {a.number}: {PRODUCTS[a.product_code].name.lower()}, {_money(a.amount or 0)}.",
                          "application_id": a.id, "reason": "Требуется ваше действие", "date": a.updated_at.isoformat()})

    # Предварительное предложение: если по последнему решению рейтинг высокий, а активных заявок нет
    scored = [a for a in apps if a.scoring and a.scoring.get("grade") in ("A", "B")]
    active = [a for a in apps if Status(a.status) not in TERMINAL]
    if scored and not any(a.product_code == "OVERDRAFT" for a in active):
        last = scored[0]
        revenue = (last.scoring.get("input") or {}).get("revenue_last", 0)
        limit = int(revenue * PRODUCTS["OVERDRAFT"].revenue_share * GRADE_LIMIT_MULT[last.scoring["grade"]] // 100_000 * 100_000)
        limit = min(limit, PRODUCTS["OVERDRAFT"].max_amount)
        if limit >= PRODUCTS["OVERDRAFT"].min_amount:
            items.append({"id": "offer-overdraft", "kind": "offer", "title": f"Вам доступен овердрафт до {_money(limit)}",
                          "body": "Предварительная оценка по данным вашей последней заявки. Окончательные условия — после подачи заявки.",
                          "product_code": "OVERDRAFT", "amount": limit,
                          "reason": f"Рейтинг {last.scoring['grade']} по заявке {last.number}",
                          "date": (last.decided_at or last.updated_at).isoformat()})

    if apps:
        events = db.scalars(select(ApplicationEvent)
                            .where(ApplicationEvent.application_id.in_([a.id for a in apps]),
                                   ApplicationEvent.kind == "STATUS", ApplicationEvent.visible_to_client.is_(True))
                            .order_by(ApplicationEvent.id.desc()).limit(3))
        numbers = {a.id: a.number for a in apps}
        for e in events:
            title = STATUS_INFO[Status(e.to_status)].title if e.to_status else "Событие"
            items.append({"id": f"ev-{e.id}", "kind": "event", "title": f"{title}: {numbers[e.application_id]}",
                          "body": e.message, "application_id": e.application_id, "reason": "Изменение по вашей заявке",
                          "date": e.created_at.isoformat()})

    # Продукты из заявок и из персональных предложений: совет про овердрафт уместен, когда его предлагают
    offered = {i["product_code"] for i in items if i["kind"] == "offer"}
    profile = Profile(legal_form=company.legal_form if company else "OOO", products={a.product_code for a in apps} | offered)
    for t in rank_tips(_tips(), profile):
        items.append({"id": t["id"], "kind": "tip", "title": t["title"], "body": t["body"],
                      "reason": t["reason"], "date": t["published_at"], "relevance": t["relevance"]})

    return {"items": items}
