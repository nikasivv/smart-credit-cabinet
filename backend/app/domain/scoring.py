"""Скоринг: оценка уровня риска заёмщика.

Простая объяснимая балльная модель (scorecard). Каждый фактор даёт
фиксированный вклад в баллы, поэтому любое решение можно разложить
на причины — и для клиента, и для аналитика. Скоринг НЕ принимает
кредитное решение: это делает policy.decide().
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

SCORECARD_VERSION = "scorecard-v1.2"
BASE_SCORE = 600

GRADES: tuple[tuple[int, str, float], ...] = (
    # нижняя граница баллов, грейд, оценочная вероятность дефолта
    (700, "A", 0.015),
    (640, "B", 0.03),
    (580, "C", 0.06),
    (520, "D", 0.12),
    (-10_000, "E", 0.25),
)

# Отраслевой риск по префиксу ОКВЭД: (класс риска, типичная маржа свободного денежного потока)
INDUSTRY_RISK: dict[str, tuple[str, float]] = {
    "62": ("low", 0.14), "63": ("low", 0.14), "69": ("low", 0.13), "86": ("low", 0.12),
    "10": ("medium", 0.10), "47": ("medium", 0.08), "46": ("medium", 0.07), "49": ("medium", 0.09),
    "01": ("medium", 0.10), "52": ("medium", 0.09),
    "56": ("high", 0.09), "41": ("high", 0.07), "43": ("high", 0.07), "68": ("high", 0.08),
}


def industry_profile(okved: str | None) -> tuple[str, float]:
    if not okved:
        return ("medium", 0.09)
    return INDUSTRY_RISK.get(okved[:2], ("medium", 0.09))


@dataclass
class ScoringInput:
    legal_status: str                  # ACTIVE | LIQUIDATING | BANKRUPT | NOT_FOUND
    business_age_months: int
    okved: str | None
    revenue_last: int
    revenue_prev: int | None
    existing_monthly_payments: int
    max_overdue_days_12m: int
    current_overdue_amount: int
    inquiries_30d: int
    tax_arrears: int
    mass_address: bool
    director_disqualified: bool


@dataclass
class Factor:
    code: str
    title: str
    value: str
    points: int
    client_text: str

    @property
    def impact(self) -> str:
        return "positive" if self.points > 0 else "negative" if self.points < 0 else "neutral"

    def to_dict(self) -> dict:
        return {**asdict(self), "impact": self.impact}


@dataclass
class StopFactor:
    code: str
    title: str
    client_text: str


@dataclass
class ScoreResult:
    score: int
    grade: str
    pd: float
    factors: list[Factor]
    stop_factors: list[StopFactor]
    version: str = SCORECARD_VERSION

    def to_dict(self) -> dict:
        return {
            "score": self.score, "grade": self.grade, "pd": self.pd, "version": self.version,
            "factors": [f.to_dict() for f in self.factors],
            "stop_factors": [asdict(s) for s in self.stop_factors],
        }


def _stop_factors(i: ScoringInput) -> list[StopFactor]:
    out: list[StopFactor] = []
    if i.legal_status == "NOT_FOUND":
        out.append(StopFactor("not_found", "Компания не найдена в ЕГРЮЛ/ЕГРИП",
                              "Банк не нашёл компанию с таким ИНН в государственном реестре."))
    if i.legal_status == "LIQUIDATING":
        out.append(StopFactor("liquidation", "Компания в процессе ликвидации",
                              "По данным ЕГРЮЛ компания находится в процессе ликвидации."))
    if i.legal_status == "BANKRUPT":
        out.append(StopFactor("bankruptcy", "Процедура банкротства",
                              "В отношении компании ведётся процедура банкротства."))
    if i.director_disqualified:
        out.append(StopFactor("disqualified_director", "Дисквалифицированный руководитель",
                              "Руководитель компании числится в реестре дисквалифицированных лиц."))
    if i.max_overdue_days_12m > 90 or (i.current_overdue_amount > 0 and i.max_overdue_days_12m > 30):
        out.append(StopFactor("serious_overdue", "Серьёзная просрочка",
                              "В кредитной истории есть просрочка более 90 дней или действующая просрочка."))
    if i.business_age_months < 3:
        out.append(StopFactor("too_young", "Бизнесу меньше 3 месяцев",
                              "Банк кредитует бизнес, который работает не менее 3 месяцев."))
    return out


def _fmt_money(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} млн ₽".replace(".", ",")
    return f"{n:,} ₽".replace(",", " ")


def score(i: ScoringInput) -> ScoreResult:
    f: list[Factor] = []

    # 1. Возраст бизнеса
    age = i.business_age_months
    years = f"{age // 12} г. {age % 12} мес." if age >= 12 else f"{age} мес."
    if age < 12:
        f.append(Factor("business_age", "Возраст бизнеса", years, -40, "Бизнес работает меньше года — истории пока мало."))
    elif age < 36:
        f.append(Factor("business_age", "Возраст бизнеса", years, 0, "Бизнес работает от года до трёх лет."))
    elif age < 72:
        f.append(Factor("business_age", "Возраст бизнеса", years, 30, "Бизнес работает больше трёх лет."))
    else:
        f.append(Factor("business_age", "Возраст бизнеса", years, 50, "Бизнес работает больше шести лет — это надёжный признак."))

    # 2. Динамика выручки
    if i.revenue_prev and i.revenue_prev > 0:
        growth = (i.revenue_last - i.revenue_prev) / i.revenue_prev
        val = f"{growth:+.0%}"
        if growth > 0.10:
            f.append(Factor("revenue_trend", "Динамика выручки", val, 40, "Выручка растёт."))
        elif growth >= -0.10:
            f.append(Factor("revenue_trend", "Динамика выручки", val, 20, "Выручка стабильна."))
        elif growth >= -0.30:
            f.append(Factor("revenue_trend", "Динамика выручки", val, -20, "Выручка снизилась по сравнению с прошлым годом."))
        else:
            f.append(Factor("revenue_trend", "Динамика выручки", val, -60, "Выручка сильно снизилась."))
    else:
        f.append(Factor("revenue_trend", "Динамика выручки", "нет данных", -10, "Нет данных о выручке за позапрошлый год."))

    # 3. Долговая нагрузка: годовые платежи по текущим долгам к выручке
    load = (i.existing_monthly_payments * 12) / i.revenue_last if i.revenue_last > 0 else 1.0
    val = f"{load:.0%} выручки"
    if load < 0.10:
        f.append(Factor("debt_load", "Долговая нагрузка", val, 40, "Текущие кредиты почти не нагружают бизнес."))
    elif load < 0.25:
        f.append(Factor("debt_load", "Долговая нагрузка", val, 10, "Долговая нагрузка умеренная."))
    elif load < 0.40:
        f.append(Factor("debt_load", "Долговая нагрузка", val, -30, "Платежи по текущим кредитам занимают заметную часть выручки."))
    else:
        f.append(Factor("debt_load", "Долговая нагрузка", val, -70, "Платежи по текущим кредитам занимают большую часть выручки."))

    # 4. Платёжная дисциплина (БКИ)
    od = i.max_overdue_days_12m
    if od == 0:
        f.append(Factor("payment_discipline", "Платёжная дисциплина", "без просрочек", 60, "За последний год не было просрочек."))
    elif od <= 30:
        f.append(Factor("payment_discipline", "Платёжная дисциплина", f"просрочка до {od} дн.", -10, "Были небольшие просрочки по платежам."))
    elif od <= 90:
        f.append(Factor("payment_discipline", "Платёжная дисциплина", f"просрочка {od} дн.", -80, "Была просрочка больше месяца."))
    else:
        f.append(Factor("payment_discipline", "Платёжная дисциплина", f"просрочка {od} дн.", -150, "Была просрочка больше 90 дней."))

    # 5. Кредитная активность
    q = i.inquiries_30d
    if q >= 5:
        f.append(Factor("inquiries", "Запросы в БКИ за 30 дней", str(q), -30, "Компания недавно подала много заявок в разные банки."))
    elif q >= 3:
        f.append(Factor("inquiries", "Запросы в БКИ за 30 дней", str(q), -10, "Несколько недавних заявок в другие банки."))
    else:
        f.append(Factor("inquiries", "Запросы в БКИ за 30 дней", str(q), 0, "Кредитная активность обычная."))

    # 6. Отрасль
    risk, _ = industry_profile(i.okved)
    pts = {"low": 10, "medium": 0, "high": -25}[risk]
    label = {"low": "низкий", "medium": "средний", "high": "повышенный"}[risk]
    f.append(Factor("industry", "Отраслевой риск", f"{label} (ОКВЭД {i.okved or '—'})", pts,
                    {"low": "Отрасль с устойчивым спросом.", "medium": "Отрасль со средним уровнем риска.",
                     "high": "В отрасли выше колебания выручки."}[risk]))

    # 7. Налоги и адрес
    if i.tax_arrears > 0:
        f.append(Factor("tax_arrears", "Налоговая задолженность", _fmt_money(i.tax_arrears), -30,
                        "По данным ФНС есть задолженность по налогам."))
    if i.mass_address:
        f.append(Factor("mass_address", "Адрес массовой регистрации", "да", -20,
                        "Компания зарегистрирована по адресу массовой регистрации."))

    total = BASE_SCORE + sum(x.points for x in f)
    grade, pd = next((g, p) for lo, g, p in GRADES if total >= lo)
    return ScoreResult(score=total, grade=grade, pd=pd, factors=f, stop_factors=_stop_factors(i))
