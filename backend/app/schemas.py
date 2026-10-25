"""Контракты API. Из них FastAPI генерирует OpenAPI (/openapi.json, /docs)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Money = int
# Верхние границы сумм: защищают от опечаток и переполнения, с запасом выше любого МСБ
MAX_REVENUE = 100_000_000_000
MAX_MONTHLY_DEBT = 10_000_000_000


class Problem(BaseModel):
    code: str
    message: str
    details: list[dict] = []
    request_id: str | None = None


# ---------- auth ----------

class LoginIn(BaseModel):
    email: str = Field(examples=["bakery@demo.ru"])
    password: str = Field(examples=["demo12345"])


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    inn: str
    name: str
    legal_form: str
    okved: str | None
    okved_name: str | None
    region: str | None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    full_name: str
    position: str | None
    role: str
    company: CompanyOut | None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- каталог ----------

class ProductOut(BaseModel):
    code: str
    name: str
    tagline: str
    description: str
    min_amount: Money
    max_amount: Money
    min_term: int
    max_term: int
    base_rate: float
    requires_collateral: bool
    purposes: list[str]
    features: list[str]


class PurposeOut(BaseModel):
    code: str
    title: str
    hint: str


class CatalogOut(BaseModel):
    version: str
    products: list[ProductOut]
    purposes: list[PurposeOut]
    documents: dict[str, str]


class CalcIn(BaseModel):
    product_code: str
    amount: Money = Field(gt=0, le=1_000_000_000)
    term_months: int = Field(gt=0, le=120)


class CalcOut(BaseModel):
    rate_from: float
    monthly_payment_from: Money
    overpayment_from: Money
    note: str


class SuggestIn(BaseModel):
    text: str | None = Field(None, max_length=1000, examples=["Нужно купить новую печь для пекарни, примерно 2,5 млн"])
    purpose: str | None = None
    amount: Money | None = Field(None, ge=0, le=1_000_000_000)


# ---------- заявки ----------

class ApplicationIn(BaseModel):
    product_code: str | None = None
    purpose: str | None = None
    purpose_comment: str | None = Field(None, max_length=2000)
    amount: Money | None = Field(None, ge=0, le=1_000_000_000)
    term_months: int | None = Field(None, ge=1, le=120)
    revenue_last_year: Money | None = Field(None, ge=0, le=MAX_REVENUE)
    revenue_prev_year: Money | None = Field(None, ge=0, le=MAX_REVENUE)
    monthly_debt_payments: Money | None = Field(None, ge=0, le=MAX_MONTHLY_DEBT)
    collateral_type: str | None = Field(None, max_length=64)
    collateral_value: Money | None = Field(None, ge=0, le=MAX_REVENUE)


class ApplicationPatch(ApplicationIn):
    version: int | None = Field(None, description="Ожидаемая версия заявки (оптимистическая блокировка)")


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    doc_type: str
    filename: str
    content_type: str
    size: int
    sha256: str
    created_at: datetime


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    from_status: str | None
    to_status: str | None
    actor_type: str
    message: str
    payload: dict | None
    created_at: datetime


class StatusView(BaseModel):
    code: str
    title: str
    now: str
    next_step: str
    waiting_for: str
    stage: int
    stages: list[str]
    allowed_actions: list[str]


class InfoRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    message: str
    items: list[dict] | None
    status: str
    requested_by_type: str
    created_at: datetime


class ApplicationOut(BaseModel):
    id: str
    number: str
    product_code: str
    product_name: str
    purpose: str | None
    purpose_comment: str | None
    amount: Money | None
    term_months: int | None
    revenue_last_year: Money | None
    revenue_prev_year: Money | None
    monthly_debt_payments: Money | None
    collateral_type: str | None
    collateral_value: Money | None
    status: StatusView
    version: int
    offer: dict | None
    decision: dict | None = Field(None, description="Решение и объяснение для клиента")
    score: dict | None = Field(None, description="Рейтинг и факторы (без внутренних лимитов)")
    contract_number: str | None
    required_documents: list[dict]
    documents: list[DocumentOut]
    info_request: InfoRequestOut | None
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    decided_at: datetime | None
    issued_at: datetime | None


class InfoResponseIn(BaseModel):
    message: str | None = Field(None, max_length=2000)
    revenue_last_year: Money | None = Field(None, ge=0, le=MAX_REVENUE)
    revenue_prev_year: Money | None = Field(None, ge=0, le=MAX_REVENUE)
    monthly_debt_payments: Money | None = Field(None, ge=0, le=MAX_MONTHLY_DEBT)
    collateral_value: Money | None = Field(None, ge=0, le=MAX_REVENUE)


class SignIn(BaseModel):
    confirmation_inn: str = Field(description="ИНН компании для подтверждения подписи")
    agree: Literal[True]


class CancelIn(BaseModel):
    reason: str | None = Field(None, max_length=500)


# ---------- аналитик ----------

class QueueItem(BaseModel):
    id: str
    number: str
    company_name: str
    company_inn: str
    product_name: str
    amount: Money | None
    term_months: int | None
    status: str
    status_title: str
    grade: str | None
    score: int | None
    analyst_id: int | None
    analyst_name: str | None
    submitted_at: datetime | None
    waiting_minutes: int | None
    reasons: list[str]


class AnalystApplicationOut(BaseModel):
    application: ApplicationOut
    company: CompanyOut
    applicant: dict
    enrichment: dict | None
    scoring: dict | None
    decision: dict | None
    summary: list[str]
    events: list[EventOut]
    analyst_id: int | None


class AnalystDecisionIn(BaseModel):
    outcome: Literal["APPROVED", "COUNTER_OFFER", "REJECTED"]
    comment: str = Field(min_length=5, max_length=2000, description="Обоснование — увидит клиент")
    amount: Money | None = Field(None, gt=0, le=1_000_000_000)
    term_months: int | None = Field(None, gt=0, le=120)
    rate: float | None = Field(None, gt=0, lt=100)


class AnalystInfoRequestIn(BaseModel):
    message: str = Field(min_length=5, max_length=2000)
    documents: list[str] = []