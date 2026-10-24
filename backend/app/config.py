"""Конфигурация из переменных окружения (12-factor)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("APP_ENV", "local")
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://scc:scc@localhost:5432/scc")
    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-in-production-please-32b")
    jwt_ttl_minutes: int = int(os.getenv("JWT_TTL_MINUTES", "480"))
    cors_origins: tuple[str, ...] = tuple(o for o in os.getenv("CORS_ORIGINS", "http://localhost:8080").split(",") if o)

    integrations_url: str = os.getenv("INTEGRATIONS_URL", "http://localhost:8090")
    integrations_timeout_sec: float = float(os.getenv("INTEGRATIONS_TIMEOUT_SEC", "3"))
    integrations_retries: int = int(os.getenv("INTEGRATIONS_RETRIES", "2"))

    # inline — обработка в процессе API (тесты); worker — отдельный воркер через очередь в БД
    pipeline_mode: str = os.getenv("PIPELINE_MODE", "worker")
    # искусственная пауза между шагами конвейера, чтобы на демо было видно движение статусов
    pipeline_step_delay_sec: float = float(os.getenv("PIPELINE_STEP_DELAY_SEC", "1.5"))
    worker_poll_interval_sec: float = float(os.getenv("WORKER_POLL_INTERVAL_SEC", "0.5"))
    job_max_attempts: int = int(os.getenv("JOB_MAX_ATTEMPTS", "5"))

    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    auto_decision_limit: int = int(os.getenv("AUTO_DECISION_LIMIT", "15000000"))

    llm_url: str = os.getenv("LLM_URL", "")            # например http://ollama:11434
    llm_model: str = os.getenv("LLM_MODEL", "qwen2.5:1.5b")
    llm_timeout_sec: float = float(os.getenv("LLM_TIMEOUT_SEC", "20"))
    seed_demo_data: bool = _bool("SEED_DEMO_DATA", True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.env == "production" and s.jwt_secret.startswith("change-me"):
        raise RuntimeError("JWT_SECRET must be set in production")
    return s
