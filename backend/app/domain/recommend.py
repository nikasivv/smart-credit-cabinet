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
    "equipment": ("оборудован", "станок", "печь", "печи", "машин", "автомоб", "транспорт", "техник", "грузовик",
                  "фургон", "газел", "тягач", "погрузчик", "трактор", "автопарк", "парк"),
    "expansion": ("точк", "филиал", "открыть", "ремонт", "помещен", "расшир"),
    "urgent": ("срочно", "быстро", "небольш"),
}


def purpose_scores(text: str) -> dict[str, int]:
    """Сколько ключевых слов каждой цели нашлось в тексте."""
    t = text.lower()
    return {code: sum(1 for kw in kws if kw in t) for code, kws in KEYWORDS.items()}


def purpose_from_text(text: str) -> str | None:
    scores = purpose_scores(text)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


_UNIT = r"(млн|миллион\w*|тыс\w*|к\b)"


def _scale(unit: str) -> int:
    return 1_000_000 if unit.startswith("м") else 1_000


def amount_from_text(text: str) -> int | None:
    """Сумма из текста: «3 млн», «2,5 миллиона», «800 тыс.», «тысяч 800», «полтора миллиона»."""
    t = text.lower().replace("\u00a0", " ")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*" + _UNIT, t)                 # число перед единицей
    if m:
        return int(float(m.group(1).replace(",", ".")) * _scale(m.group(2)))
    m = re.search(_UNIT + r"\s*(\d+(?:[.,]\d+)?)", t)                 # «тысяч 800», «миллиона 2»
    if m:
        return int(float(m.group(2).replace(",", ".")) * _scale(m.group(1)))
    m = re.search(r"пол(?:тор|утор)\w*\s+" + _UNIT, t)                          # «полтора миллиона», «полутора млн»
    if m:
        return int(1.5 * _scale(m.group(1)))
    return None


def mentions_amount(text: str) -> bool:
    """Есть ли в тексте хоть какой-то признак суммы — цифры или слова-единицы."""
    t = text.lower()
    return bool(re.search(r"\d", t) or re.search(r"млн|миллион|тыс|полтор|полутор|сто\s|двести|триста|пятьсот|рубл|₽", t))


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