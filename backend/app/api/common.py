from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from ..config import get_settings
from ..errors import Conflict


def commit(db: Session) -> None:
    try:
        db.commit()
    except StaleDataError as e:
        db.rollback()
        raise Conflict("Заявка одновременно изменилась в другом месте. Обновите страницу и повторите действие",
                       code="version_mismatch") from e
    if get_settings().pipeline_mode == "inline":
        drain_jobs()


def drain_jobs(limit: int = 50) -> None:
    """Режим inline (тесты, локальная отладка без воркера): выполнить очередь сразу."""
    from ..worker import process_one
    for _ in range(limit):
        if not process_one(step_delay=0):
            break
