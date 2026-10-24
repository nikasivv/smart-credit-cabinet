"""Проверки заявки.

Два уровня:
* validate_for_submit — блокирующие ошибки формы, клиент не может отправить заявку;
* completeness_check — проверка полноты на стороне банка: результат —
  дозапрос информации (NEEDS_INFO), а не ошибка формы.
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
