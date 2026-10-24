from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

_settings = get_settings()
_is_sqlite = _settings.database_url.startswith("sqlite")

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    future=True,
    **({"connect_args": {"check_same_thread": False}} if _is_sqlite else {"pool_size": 10, "max_overflow": 20}),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def is_sqlite() -> bool:
    return _is_sqlite
