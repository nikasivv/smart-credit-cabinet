"""Подбор продукта под потребность клиента — детерминированные правила.

Используется всегда; LLM (если включён) лишь переводит свободный текст
клиента в код цели, а итоговый подбор делают эти правила.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .products import PRODUCTS, PURPOSES


@dataclass
class Recommendation:
    product_code: str
    fit: str          # best | alternative
    reason: str


KEYWORDS: dict[str, tuple[str, ...]] = {
    "cash_gap": ("разрыв", "отсрочк", "дебитор", "не хватает на счёт", "временно", "поступлени"),
    "inventory": ("закуп", "товар", "сырь", "партию", "сезон", "склад"),
    "contract": ("контракт", "госзаказ", "тендер", "заказ", "44-фз", "223"),
    "payroll": ("зарплат", "налог", "аванс сотрудник"),
    "equipment": ("оборудован", "станок", "печь", "печи", "машин", "автомоб", "транспорт", "техник", "грузовик"),
    "expansion": ("точк", "филиал", "открыть", "ремонт", "помещен", "расшир"),
    "urgent": ("срочно", "быстро", "небольш"),
}


def purpose_from_text(text: str) -> str | None:
    t = text.lower()
    scores = {code: sum(1 for kw in kws if kw in t) for code, kws in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


def amount_from_text(text: str) -> int | None:
    t = text.lower().replace("\u00a0", " ")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(млн|миллион|тыс|к\b)", t)
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    return int(n * (1_000_000 if m.group(2).startswith("м") else 1_000))


def recommend(purpose: str, amount: int | None = None) -> list[Recommendation]:
    recs: list[Recommendation] = []
    for code, p in PRODUCTS.items():
        if purpose not in p.purposes:
            continue
        if amount and not (p.min_amount <= amount <= p.max_amount):
            continue
        recs.append(Recommendation(code, "alternative", p.tagline))

    order = {
        "equipment": ["EXPRESS", "INVESTMENT"] if amount and amount <= 3_000_000 else ["INVESTMENT", "EXPRESS"],
        "cash_gap": ["OVERDRAFT"],
        "payroll": ["OVERDRAFT", "WORKING_CAPITAL"],
    }.get(purpose, [])
    recs.sort(key=lambda r: order.index(r.product_code) if r.product_code in order else 99)

    if not recs:  # ничего не подошло по сумме — предлагаем ближайший по цели продукт
        for code, p in PRODUCTS.items():
            if purpose in p.purposes:
                recs.append(Recommendation(code, "alternative",
                                           f"Сумма по этому продукту — до {p.max_amount // 1_000_000} млн ₽"))
    if recs:
        recs[0].fit = "best"
        recs[0].reason = _why_best(recs[0].product_code, purpose, amount)
    return recs


def _why_best(code: str, purpose: str, amount: int | None) -> str:
    title = PURPOSES[purpose].title.lower()
    return {
        "OVERDRAFT": f"Чтобы {title}, удобнее всего овердрафт: платите проценты только за дни, когда деньги использованы.",
        "WORKING_CAPITAL": f"Чтобы {title}, подходит оборотный кредит: вся сумма сразу и понятный график платежей.",
        "INVESTMENT": f"Чтобы {title}, выгоднее инвестиционный кредит: длинный срок и ниже ставка за счёт залога.",
        "EXPRESS": f"Для небольшой суммы быстрее всего экспресс-кредит: без залога и с минимумом документов.",
    }[code]
