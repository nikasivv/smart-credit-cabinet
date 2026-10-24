"""Каталог продуктов, целей финансирования и документов.

Продуктовые параметры хранятся как версионируемая конфигурация в коде:
изменения проходят ревью и попадают в историю коммитов.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PRODUCT_CATALOG_VERSION = "products-2026.10"


@dataclass(frozen=True)
class Product:
    code: str
    name: str
    tagline: str
    description: str
    min_amount: int
    max_amount: int
    min_term: int
    max_term: int
    base_rate: float           # годовая ставка, %
    revenue_share: float       # максимальная доля годовой выручки в лимите
    requires_collateral: bool
    required_docs: tuple[str, ...] = ()
    purposes: tuple[str, ...] = ()
    features: tuple[str, ...] = field(default_factory=tuple)


DOCUMENTS: dict[str, str] = {
    "financial_statements": "Бухгалтерская отчётность за последний год",
    "bank_statements": "Выписка по счетам в других банках за 6 месяцев",
    "collateral_docs": "Документы на залоговое имущество",
    "contract": "Договор или спецификация на покупку",
    "other": "Другой документ",
}

# Отчётность нужна для сумм свыше порога — по любому продукту.
FINANCIAL_STATEMENTS_THRESHOLD = 5_000_000

PRODUCTS: dict[str, Product] = {
    p.code: p
    for p in (
        Product(
            code="OVERDRAFT",
            name="Овердрафт",
            tagline="Подстраховка, когда на счёте временно не хватает денег",
            description="Банк оплачивает платежи сверх остатка на счёте. Долг гасится автоматически с поступлений.",
            min_amount=100_000, max_amount=10_000_000, min_term=1, max_term=12,
            base_rate=21.0, revenue_share=0.15, requires_collateral=False,
            purposes=("cash_gap", "payroll"),
            features=("Без залога", "Гашение с поступлений", "Лимит возобновляется"),
        ),
        Product(
            code="WORKING_CAPITAL",
            name="Кредит на оборотные средства",
            tagline="На закупку товара, сырья и исполнение контрактов",
            description="Единовременная выдача на расчётный счёт с ежемесячными платежами.",
            min_amount=300_000, max_amount=30_000_000, min_term=3, max_term=36,
            base_rate=19.5, revenue_share=0.35, requires_collateral=False,
            purposes=("inventory", "contract", "payroll"),
            features=("Без залога до 30 млн ₽", "Срок до 3 лет", "Досрочное погашение без комиссии"),
        ),
        Product(
            code="INVESTMENT",
            name="Инвестиционный кредит",
            tagline="На оборудование, транспорт и развитие бизнеса",
            description="Длинные деньги под залог приобретаемого имущества.",
            min_amount=1_000_000, max_amount=100_000_000, min_term=12, max_term=84,
            base_rate=18.0, revenue_share=0.6, requires_collateral=True,
            required_docs=("collateral_docs", "contract"),
            purposes=("equipment", "expansion"),
            features=("Срок до 7 лет", "Залог — приобретаемое имущество", "Отсрочка первого платежа"),
        ),
        Product(
            code="EXPRESS",
            name="Экспресс-кредит",
            tagline="Небольшая сумма на любые цели бизнеса",
            description="Решение по упрощённой анкете без залога и поручителей.",
            min_amount=100_000, max_amount=5_000_000, min_term=3, max_term=24,
            base_rate=24.0, revenue_share=0.2, requires_collateral=False,
            purposes=("urgent", "equipment", "inventory"),
            features=("Без залога", "Минимум документов", "Решение за минуты"),
        ),
    )
}


@dataclass(frozen=True)
class Purpose:
    code: str
    title: str
    hint: str


PURPOSES: dict[str, Purpose] = {
    p.code: p
    for p in (
        Purpose("cash_gap", "Закрыть кассовый разрыв", "Покупатели платят с отсрочкой, а расходы — сейчас"),
        Purpose("inventory", "Закупить товар или сырьё", "Сезонная закупка, крупная партия со скидкой"),
        Purpose("contract", "Исполнить контракт", "Нужны деньги на исполнение заказа до оплаты"),
        Purpose("payroll", "Выплатить зарплаты и налоги", "Платёжный день раньше поступлений"),
        Purpose("equipment", "Купить оборудование или транспорт", "Станки, печи, автомобили, техника"),
        Purpose("expansion", "Открыть новую точку", "Ремонт, оснащение, аренда нового помещения"),
        Purpose("urgent", "Срочно нужна небольшая сумма", "До 5 млн ₽ на любые цели бизнеса"),
    )
}


def required_documents(product: Product, amount: int) -> list[str]:
    docs = list(product.required_docs)
    if amount > FINANCIAL_STATEMENTS_THRESHOLD and "financial_statements" not in docs:
        docs.append("financial_statements")
    return docs
