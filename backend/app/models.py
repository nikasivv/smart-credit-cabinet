"""Модель данных. Описание — docs/data-model.md."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (JSON, BigInteger, DateTime, ForeignKey, Index, Integer, LargeBinary, String,
                        Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inn: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    legal_form: Mapped[str] = mapped_column(String(8))            # OOO | IP
    okved: Mapped[str | None] = mapped_column(String(16))
    okved_name: Mapped[str | None] = mapped_column(String(255))
    region: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    position: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))                 # CLIENT | ANALYST | RISK_ADMIN
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    company: Mapped[Company | None] = relationship(lazy="joined")


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    number: Mapped[str] = mapped_column(String(32), unique=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    analyst_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    product_code: Mapped[str] = mapped_column(String(32))
    purpose: Mapped[str | None] = mapped_column(String(32))
    purpose_comment: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[int | None] = mapped_column(BigInteger)
    term_months: Mapped[int | None] = mapped_column(Integer)
    revenue_last_year: Mapped[int | None] = mapped_column(BigInteger)
    revenue_prev_year: Mapped[int | None] = mapped_column(BigInteger)
    monthly_debt_payments: Mapped[int | None] = mapped_column(BigInteger)
    collateral_type: Mapped[str | None] = mapped_column(String(64))
    collateral_value: Mapped[int | None] = mapped_column(BigInteger)

    status: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    enrichment: Mapped[dict | None] = mapped_column(JSON)   # ответы ЕГРЮЛ/ФНС/БКИ
    scoring: Mapped[dict | None] = mapped_column(JSON)      # баллы и факторы
    decision: Mapped[dict | None] = mapped_column(JSON)     # решение и обоснование
    offer: Mapped[dict | None] = mapped_column(JSON)        # действующее предложение
    contract_number: Mapped[str | None] = mapped_column(String(32))
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[Company] = relationship(lazy="joined")
    documents: Mapped[list[Document]] = relationship(back_populates="application", lazy="selectin",
                                                     order_by="Document.id")

    # Оптимистическая блокировка: параллельные изменения одной заявки не затирают друг друга
    __mapper_args__ = {"version_id_col": version}


class ApplicationEvent(Base):
    """Неизменяемый журнал: каждый переход статуса и значимое действие."""
    __tablename__ = "application_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))                 # STATUS | DOCUMENT | COMMENT | INTEGRATION
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    actor_type: Mapped[str] = mapped_column(String(16))           # CLIENT | SYSTEM | ANALYST
    actor_id: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)
    visible_to_client: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(128))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    uploaded_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    application: Mapped[Application] = relationship(back_populates="documents")


class InfoRequest(Base):
    __tablename__ = "info_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    requested_by_type: Mapped[str] = mapped_column(String(16))    # SYSTEM | ANALYST
    requested_by_id: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    items: Mapped[list | None] = mapped_column(JSON)
    response_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN | ANSWERED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Base):
    """Очередь задач в БД (transactional outbox): задача создаётся в той же
    транзакции, что и смена статуса, поэтому не теряется при сбое."""
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))                 # PROCESS_APPLICATION | DISBURSE
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING | RUNNING | DONE | FAILED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)
