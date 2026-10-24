"""Начальная схема кредитного конвейера

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("inn", sa.String(12), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("legal_form", sa.String(8), nullable=False),
        sa.Column("okved", sa.String(16)),
        sa.Column("okved_name", sa.String(255)),
        sa.Column("region", sa.String(128)),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_companies_inn", "companies", ["inn"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("position", sa.String(128)),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id")),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("number", sa.String(32), nullable=False, unique=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("applicant_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("analyst_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("product_code", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(32)),
        sa.Column("purpose_comment", sa.Text),
        sa.Column("amount", sa.BigInteger),
        sa.Column("term_months", sa.Integer),
        sa.Column("revenue_last_year", sa.BigInteger),
        sa.Column("revenue_prev_year", sa.BigInteger),
        sa.Column("monthly_debt_payments", sa.BigInteger),
        sa.Column("collateral_type", sa.String(64)),
        sa.Column("collateral_value", sa.BigInteger),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("enrichment", sa.JSON),
        sa.Column("scoring", sa.JSON),
        sa.Column("decision", sa.JSON),
        sa.Column("offer", sa.JSON),
        sa.Column("contract_number", sa.String(32)),
        sa.Column("idempotency_key", sa.String(64), unique=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("submitted_at", TS),
        sa.Column("decided_at", TS),
        sa.Column("issued_at", TS),
    )
    op.create_index("ix_applications_company_id", "applications", ["company_id"])
    op.create_index("ix_applications_status", "applications", ["status"])

    op.create_table(
        "application_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("from_status", sa.String(32)),
        sa.Column("to_status", sa.String(32)),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.Integer),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("payload", sa.JSON),
        sa.Column("visible_to_client", sa.Boolean, nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_application_events_application_id", "application_events", ["application_id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("doc_type", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("uploaded_by", sa.Integer, nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_documents_application_id", "documents", ["application_id"])

    op.create_table(
        "info_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("requested_by_type", sa.String(16), nullable=False),
        sa.Column("requested_by_id", sa.Integer),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("items", sa.JSON),
        sa.Column("response_text", sa.Text),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("answered_at", TS),
    )
    op.create_index("ix_info_requests_application_id", "info_requests", ["application_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("run_after", TS, nullable=False),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("ix_jobs_status_run_after", "jobs", ["status", "run_after"])


def downgrade() -> None:
    for t in ("jobs", "info_requests", "documents", "application_events", "applications", "users", "companies"):
        op.drop_table(t)
