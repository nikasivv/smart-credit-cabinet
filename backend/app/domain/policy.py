"""Кредитное решение поверх скоринга.

Скоринг говорит «насколько рискованный заёмщик», политика — «что ему
можно предложить по конкретному продукту». Поэтому одинаковый грейд
даёт разные условия для разных продуктов.

Алгоритм:
1. Стоп-факторы → отказ.
2. Грейд E → отказ; грейд D или сумма выше лимита автоматического
   решения → ручное рассмотрение (с рекомендацией системы).
3. Ставка = базовая ставка продукта + надбавка за грейд.
4. Лимит = min(макс. по продукту, доля выручки × коэффициент грейда,
   сумма, которую бизнес способен обслуживать при DSCR ≥ 1,25).
5. Хватает лимита → одобрение. Не хватает → пробуем увеличить срок,
   затем уменьшить сумму (встречное предложение). Иначе — отказ.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .products import Product
from .scoring import ScoreResult, ScoringInput, industry_profile
from .statuses import Status

POLICY_VERSION = "policy-2026.10"
AUTO_DECISION_LIMIT = 15_000_000   # выше — только ручное рассмотрение
MIN_DSCR = 1.25                    # денежный поток / платежи по долгу
COUNTER_MIN_SHARE = 0.3            # встречное предложение не меньше 30% запрошенного

GRADE_RATE_PREMIUM = {"A": 0.0, "B": 1.5, "C": 3.0, "D": 4.5, "E": 8.0}
GRADE_LIMIT_MULT = {"A": 1.0, "B": 0.85, "C": 0.65, "D": 0.45, "E": 0.0}


@dataclass
class Offer:
    amount: int
    term_months: int
    rate: float
    monthly_payment: int
    overpayment: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Decision:
    outcome: Status                       # APPROVED | COUNTER_OFFER | REJECTED | MANUAL_REVIEW
    offer: Offer | None
    reasons: list[str]
    client_explanation: str
    recommended_outcome: Status | None = None   # для MANUAL_REVIEW — что предложила система
    limits: dict = field(default_factory=dict)
    policy_version: str = POLICY_VERSION

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "offer": self.offer.to_dict() if self.offer else None,
            "reasons": self.reasons,
            "client_explanation": self.client_explanation,
            "recommended_outcome": self.recommended_outcome.value if self.recommended_outcome else None,
            "limits": self.limits,
            "policy_version": self.policy_version,
        }


def annuity_payment(amount: float, annual_rate: float, term: int) -> int:
    r = annual_rate / 100 / 12
    if r == 0:
        return math.ceil(amount / term)
    return math.ceil(amount * r / (1 - (1 + r) ** -term))


def max_amount_for_payment(payment: float, annual_rate: float, term: int) -> int:
    if payment <= 0:
        return 0
    r = annual_rate / 100 / 12
    if r == 0:
        return int(payment * term)
    return int(payment * (1 - (1 + r) ** -term) / r)


def make_offer(amount: int, term: int, rate: float) -> Offer:
    p = annuity_payment(amount, rate, term)
    return Offer(amount=amount, term_months=term, rate=round(rate, 2), monthly_payment=p, overpayment=p * term - amount)


def _round_down(n: float, step: int = 10_000) -> int:
    return int(n // step * step)


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₽"


def capacity_limit(inp: ScoringInput, rate: float, term: int) -> int:
    """Сколько бизнес может занять, сохранив DSCR ≥ 1,25."""
    _, margin = industry_profile(inp.okved)
    monthly_cash_flow = inp.revenue_last / 12 * margin
    available_payment = monthly_cash_flow / MIN_DSCR - inp.existing_monthly_payments
    return max_amount_for_payment(available_payment, rate, term)


def decide(product: Product, amount: int, term: int, s: ScoreResult, inp: ScoringInput,
           auto_limit: int = AUTO_DECISION_LIMIT) -> Decision:
    # 1. Стоп-факторы
    if s.stop_factors:
        return Decision(
            outcome=Status.REJECTED, offer=None,
            reasons=[sf.title for sf in s.stop_factors],
            client_explanation="Банк не может выдать финансирование: " + " ".join(sf.client_text for sf in s.stop_factors),
        )
    if s.grade == "E":
        negatives = [f.client_text for f in s.factors if f.points < 0]
        return Decision(
            outcome=Status.REJECTED, offer=None, reasons=[f"Кредитный рейтинг {s.grade} ниже порога одобрения"],
            client_explanation="Сейчас риск по заявке выше допустимого. Основные причины: " + " ".join(negatives),
        )

    rate = product.base_rate + GRADE_RATE_PREMIUM[s.grade]
    by_revenue = _round_down(inp.revenue_last * product.revenue_share * GRADE_LIMIT_MULT[s.grade])
    by_capacity = _round_down(capacity_limit(inp, rate, term))
    limit = min(product.max_amount, by_revenue, by_capacity)
    limits = {"product_max": product.max_amount, "by_revenue": by_revenue,
              "by_capacity": by_capacity, "final": limit, "rate": rate}

    proposal = _propose(product, amount, term, rate, inp, by_revenue, limit, limits)

    # 2. Маршрутизация на ручное рассмотрение
    manual_reasons = []
    if s.grade == "D":
        manual_reasons.append(f"Рейтинг {s.grade}: пограничный риск — нужна экспертная оценка")
    if amount > auto_limit:
        manual_reasons.append(f"Сумма выше лимита автоматического решения {_fmt(auto_limit)}")
    if manual_reasons and proposal.outcome != Status.REJECTED:
        return Decision(
            outcome=Status.MANUAL_REVIEW, offer=proposal.offer, reasons=manual_reasons + proposal.reasons,
            client_explanation="Заявку посмотрит кредитный специалист — это стандартная процедура для таких параметров.",
            recommended_outcome=proposal.outcome, limits=limits,
        )
    return proposal


def _propose(product: Product, amount: int, term: int, rate: float, inp: ScoringInput,
             by_revenue: int, limit: int, limits: dict) -> Decision:
    if amount <= limit:
        return Decision(
            outcome=Status.APPROVED, offer=make_offer(amount, term, rate), limits=limits,
            reasons=["Запрошенная сумма в пределах лимита"],
            client_explanation=f"Банк одобрил {_fmt(amount)} на {term} мес. по ставке {rate:.1f}% годовых.",
        )

    # Попытка 1: та же сумма, но дольше срок → ниже платёж
    if amount <= min(product.max_amount, by_revenue):
        for t in range(term + 1, product.max_term + 1):
            if capacity_limit(inp, rate, t) >= amount:
                return Decision(
                    outcome=Status.COUNTER_OFFER, offer=make_offer(amount, t, rate), limits=limits,
                    reasons=[f"Платёж на {term} мес. превышает платёжеспособность; срок увеличен до {t} мес."],
                    client_explanation=(f"Банк готов выдать всю сумму {_fmt(amount)}, но на {t} мес. вместо {term}: "
                                        "так ежемесячный платёж будет посильным для вашей выручки."),
                )

    # Попытка 2: меньшая сумма на максимальном доступном сроке
    best_term = product.max_term
    best_cap = _round_down(capacity_limit(inp, rate, best_term))
    reduced = min(product.max_amount, by_revenue, best_cap)
    # не растягиваем срок без необходимости
    for t in range(term, product.max_term + 1):
        if _round_down(capacity_limit(inp, rate, t)) >= reduced:
            best_term = t
            break
    if reduced >= product.min_amount and reduced >= amount * COUNTER_MIN_SHARE:
        why = ("с учётом годовой выручки" if reduced == by_revenue
               else "чтобы платёж был посильным для денежного потока бизнеса с учётом текущих кредитов")
        return Decision(
            outcome=Status.COUNTER_OFFER, offer=make_offer(reduced, best_term, rate), limits=limits,
            reasons=[f"Лимит {_fmt(reduced)} ниже запрошенной суммы {_fmt(amount)}"],
            client_explanation=(f"Банк готов выдать {_fmt(reduced)} вместо {_fmt(amount)} {why}. "
                                f"Срок — {best_term} мес."),
        )

    return Decision(
        outcome=Status.REJECTED, offer=None, limits=limits,
        reasons=["Доступный лимит ниже минимальной суммы продукта"],
        client_explanation=("Текущая выручка и платежи по действующим кредитам не позволяют обслуживать новый кредит. "
                            "Можно подать заявку снова после погашения части текущих долгов."),
    )
