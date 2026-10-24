"""Сидер демо-данных: история создаётся полностью или не создаётся вовсе."""
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Application
from app.seed import SeedIncomplete, seed_history, seed_users, wipe_history


@pytest.fixture()
def fresh_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/seed.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_seed_history_complete(fresh_db, gateway):
    users = seed_users(fresh_db)
    seed_history(fresh_db, users)
    statuses = sorted(fresh_db.scalars(select(Application.status)))
    assert statuses == ["ISSUED", "MANUAL_REVIEW"]


def test_seed_history_rolls_back_when_sources_down(fresh_db, gateway):
    gateway.down = {"egrul", "fns", "bki"}
    users = seed_users(fresh_db)
    created: list[str] = []
    with pytest.raises(SeedIncomplete):
        seed_history(fresh_db, users, created)
    fresh_db.rollback()
    wipe_history(fresh_db, created)
    assert fresh_db.scalar(select(func.count()).select_from(Application)) == 0
    # После восстановления источников следующий запуск создаёт историю заново
    gateway.down = set()
    seed_history(fresh_db, users)
    assert sorted(fresh_db.scalars(select(Application.status))) == ["ISSUED", "MANUAL_REVIEW"]
