"""Проверки заявки.

Два уровня:
* validate_for_submit — блокирующие ошибки формы, клиент не может отправить заявку;
* completeness_check — проверка полноты на стороне банка: результат —
  дозапрос информации (NEEDS_INFO), а не ошибка формы.

sanity_check — правдоподобность цифр (выручка «13 ₽», платежи больше выручки).
Это почти всегда опечатка, поэтому ловим её сразу на шаге «О бизнесе», а не дозапросом.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .products import DOCUMENTS, Product, required_documents


@dataclass(frozen=True)
class Issue:
    field: str
    code: str
    message: str


@dataclass
class ApplicationData:
    product_code: str
    amount: int | None
    term_months: int | None
    purpose: str | None
    revenue_last_year: int | None
    revenue_prev_year: int | None
    monthly_debt_payments: int | None
    collateral_type: str | None = None
    collateral_value: int | None = None
    documents: set[str] = field(default_factory=set)


def inn_is_valid(inn: str) -> bool:
    """Проверка контрольных цифр ИНН (10 знаков — ЮЛ, 12 — ИП)."""
    if not inn.isdigit() or len(inn) not in (10, 12):
        return False
    d = [int(c) for c in inn]

    def check(coeffs: list[int]) -> int:
        return sum(x * k for x, k in zip(d, coeffs)) % 11 % 10

    if len(inn) == 10:
        return check([2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[9]
    return (check([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[10]
            and check([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[11])


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₽"


# Меньше 10 000 ₽ за год — почти наверняка опечатка: ввели в тысячах или миллионах («13» вместо 13 000 000).
# Порог низкий намеренно: маленький ИП с выручкой в десятки тысяч должен дойти до рассмотрения —
# небольшой лимит или отказ ему даст кредитная логика, а не ошибка формы.
MIN_REVENUE = 10_000


def sanity_check(data: ApplicationData) -> list[Issue]:
    """Неправдоподобные финансовые показатели. Пустые поля не проверяет — за них отвечает validate_for_submit."""
    issues: list[Issue] = []
    for f, year in (("revenue_last_year", "прошлый"), ("revenue_prev_year", "позапрошлый")):
        v = getattr(data, f)
        if v is not None and 0 < v < MIN_REVENUE:
            issues.append(Issue(f, "implausible",
                                f"Выручка за {year} год — {_fmt(v)}? Укажите сумму полностью в рублях: "
                                f"например, 13 млн — это 13 000 000"))
    rev, debt = data.revenue_last_year, data.monthly_debt_payments
    if rev and rev >= MIN_REVENUE and debt and debt * 12 > rev:
        issues.append(Issue("monthly_debt_payments", "exceeds_revenue",
                            f"Платежи по кредитам за год ({_fmt(debt * 12)}) больше выручки ({_fmt(rev)}). "
                            "Проверьте: платежи указываются в месяц, выручка — за год"))
    return issues


def validate_for_submit(data: ApplicationData, product: Product) -> list[Issue]:
    issues: list[Issue] = []
    if data.amount is None:
        issues.append(Issue("amount", "required", "Укажите сумму"))
    elif not product.min_amount <= data.amount <= product.max_amount:
        issues.append(Issue("amount", "out_of_range",
                            f"Сумма по продукту «{product.name}» — от {_fmt(product.min_amount)} до {_fmt(product.max_amount)}"))
    if data.term_months is None:
        issues.append(Issue("term_months", "required", "Укажите срок"))
    elif not product.min_term <= data.term_months <= product.max_term:
        issues.append(Issue("term_months", "out_of_range",
                            f"Срок — от {product.min_term} до {product.max_term} мес."))
    if not data.purpose:
        issues.append(Issue("purpose", "required", "Укажите цель финансирования"))
    if data.revenue_last_year is None or data.revenue_last_year <= 0:
        issues.append(Issue("revenue_last_year", "required", "Укажите выручку за прошлый год"))
    if data.monthly_debt_payments is None or data.monthly_debt_payments < 0:
        issues.append(Issue("monthly_debt_payments", "required",
                            "Укажите ежемесячные платежи по текущим кредитам (0, если кредитов нет)"))
    if product.requires_collateral:
        if not data.collateral_type:
            issues.append(Issue("collateral_type", "required", "Укажите, что будет в залоге"))
        if not data.collateral_value or data.collateral_value <= 0:
            issues.append(Issue("collateral_value", "required", "Укажите оценочную стоимость залога"))
    issues.extend(i for i in sanity_check(data) if i.field not in {x.field for x in issues})
    return issues


def completeness_check(data: ApplicationData, product: Product) -> list[Issue]:
    """Чего не хватает банку для рассмотрения. Пустой список — можно двигаться дальше."""
    issues: list[Issue] = []
    for doc in required_documents(product, data.amount or 0):
        if doc not in data.documents:
            issues.append(Issue(f"documents.{doc}", "missing_document", f"Загрузите: {DOCUMENTS[doc]}"))
    if product.requires_collateral and data.collateral_value and data.amount:
        if data.collateral_value < data.amount * 0.7:
            issues.append(Issue("collateral_value", "insufficient_collateral",
                                "Стоимость залога должна покрывать не менее 70% суммы кредита. "
                                "Уточните оценку или добавьте имущество"))
    return issues


def revenue_discrepancy(declared: int | None, official: int | None, tolerance: float = 0.3) -> bool:
    """Заявленная клиентом выручка заметно выше данных ФНС."""
    if not declared or not official:
        return False
    return declared > official * (1 + tolerance)