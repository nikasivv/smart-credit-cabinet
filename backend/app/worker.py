"""Воркер кредитного конвейера.

Забирает задачи из таблицы jobs (SELECT … FOR UPDATE SKIP LOCKED),
поэтому можно запускать несколько экземпляров — задача достанется одному.
Ошибки повторяются с экспоненциальной задержкой, после исчерпания
попыток задача помечается FAILED и видна в /api/admin/jobs.

Запуск: python -m app.worker
"""
from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal, is_sqlite
from .logging_setup import setup_logging
from .models import Job
from .services.pipeline import run_job

log = logging.getLogger("scc.worker")
_running = True
# Файл-«пульс» для проверки здоровья контейнера: воркер обновляет его на каждом круге цикла.
HEARTBEAT_FILE = Path(os.getenv("WORKER_HEARTBEAT_FILE", "/tmp/scc-worker-heartbeat"))


def heartbeat() -> None:
    try:
        HEARTBEAT_FILE.touch()
    except OSError:  # нет прав на запись — проверка здоровья просто не пройдёт, работу это не ломает
        pass


def is_alive(max_age_sec: float = 120) -> bool:
    """Проверка для HEALTHCHECK: пульс обновлялся не позже max_age_sec назад."""
    try:
        return time.time() - HEARTBEAT_FILE.stat().st_mtime < max_age_sec
    except OSError:
        return False


def _stop(*_):
    global _running
    _running = False
    log.info("worker_stopping")


def claim_job(db) -> Job | None:
    q = (select(Job).where(Job.status == "PENDING", Job.run_after <= datetime.now(UTC))
         .order_by(Job.id).limit(1))
    if not is_sqlite():
        q = q.with_for_update(skip_locked=True)
    job = db.scalar(q)
    if job:
        job.status, job.attempts = "RUNNING", job.attempts + 1
        db.commit()
    return job


def process_one(step_delay: float | None = None) -> bool:
    """Обработать одну задачу. True — задача была."""
    s = get_settings()
    with SessionLocal() as db:
        job = claim_job(db)
        if job is None:
            return False
        job_id, kind, app_id, attempts = job.id, job.kind, job.application_id, job.attempts
    log.info("job_started id=%s kind=%s attempt=%s", job_id, kind, attempts)
    with SessionLocal() as db:
        try:
            result = run_job(db, kind, app_id, step_delay=step_delay)
            job = db.get(Job, job_id)
            job.status, job.last_error = "DONE", None
            db.commit()
            log.info("job_done id=%s kind=%s status=%s", job_id, kind, result)
        except Exception as e:  # noqa: BLE001 — любая ошибка задачи должна быть зафиксирована
            db.rollback()
            job = db.get(Job, job_id)
            job.last_error = f"{type(e).__name__}: {e}"[:2000]
            if job.attempts >= s.job_max_attempts:
                job.status = "FAILED"
                log.error("job_failed id=%s kind=%s err=%s", job_id, kind, job.last_error)
            else:
                job.status = "PENDING"
                job.run_after = datetime.now(UTC) + timedelta(seconds=2 ** job.attempts)
                log.warning("job_retry id=%s kind=%s in=%ss err=%s", job_id, kind, 2 ** job.attempts, job.last_error)
            db.commit()
    return True


def recover_stuck_jobs(older_than_sec: int = 300) -> int:
    """Задачи, «застрявшие» в RUNNING после падения воркера, возвращаются в очередь."""
    with SessionLocal() as db:
        border = datetime.now(UTC) - timedelta(seconds=older_than_sec)
        stuck = list(db.scalars(select(Job).where(Job.status == "RUNNING", Job.updated_at < border)))
        for j in stuck:
            j.status = "PENDING"
        db.commit()
        return len(stuck)


def main() -> None:
    setup_logging()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    s = get_settings()
    log.info("worker_started recovered=%s", recover_stuck_jobs())
    while _running:
        heartbeat()
        try:
            if not process_one():
                time.sleep(s.worker_poll_interval_sec)
        except Exception:  # noqa: BLE001 — воркер не должен падать из-за временной ошибки БД
            log.exception("worker_loop_error")
            time.sleep(2)


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--healthcheck"]:
        sys.exit(0 if is_alive() else 1)
    main()
