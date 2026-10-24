"""Синтетические демо-данные. Идемпотентно: повторный запуск ничего не дублирует.

Запуск: python -m app.seed
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, select

from .config import get_settings
from .db import SessionLocal
from .domain.statuses import Status
from .logging_setup import setup_logging
from .models import Application, ApplicationEvent, Company, Document, InfoRequest, Job, User
from .security import hash_password
from .services import applications as svc
from .services.pipeline import Pipeline

log = logging.getLogger("scc.seed")

CLIENT_PASSWORD = "demo12345"

COMPANIES = [
    # inn, name, legal_form, okved, okved_name, region, email, full_name, position
    ("7708123450", "ООО «Северная пекарня»", "OOO", "10.71", "Производство хлеба и хлебобулочных изделий", "Москва",
     "bakery@demo.ru", "Ольга Миронова", "Генеральный директор"),
    ("500100732259", "ИП Смирнова Анна Викторовна", "IP", "56.30", "Подача напитков", "Московская область",
     "coffee@demo.ru", "Анна Смирнова", "Индивидуальный предприниматель"),
    ("5027146895", "ООО «ТрансЛогистик»", "OOO", "49.41", "Автомобильные грузоперевозки", "Московская область",
     "logistic@demo.ru", "Игорь Белов", "Финансовый директор"),
    ("7816039573", "ООО «Вектор Строй»", "OOO", "41.20", "Строительство зданий", "Санкт-Петербург",
     "build@demo.ru", "Сергей Кузнецов", "Генеральный директор"),
    ("6623018470", "ООО «Агро Плюс»", "OOO", "01.11", "Выращивание зерновых культур", "Свердловская область",
     "agro@demo.ru", "Марина Ершова", "Главный бухгалтер"),
    ("2310045622", "ООО «Код и Цифра»", "OOO", "62.01", "Разработка программного обеспечения", "Краснодарский край",
     "it@demo.ru", "Дмитрий Орлов", "Генеральный директор"),
]

STAFF = [
    ("analyst@alfa.demo", "Екатерина Волкова", "Кредитный аналитик", "ANALYST", "analyst12345"),
    ("analyst2@alfa.demo", "Павел Громов", "Кредитный аналитик", "ANALYST", "analyst12345"),
    ("risk@alfa.demo", "Алексей Соколов", "Риск-менеджер", "RISK_ADMIN", "risk12345"),
]

FAKE_PDF = b"%PDF-1.4\n% synthetic demo document\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def seed_users(db) -> dict[str, User]:
    users: dict[str, User] = {}
    for inn, name, form, okved, okved_name, region, email, full_name, position in COMPANIES:
        company = db.scalar(select(Company).where(Company.inn == inn))
        if company is None:
            company = Company(inn=inn, name=name, legal_form=form, okved=okved, okved_name=okved_name, region=region)
            db.add(company)
            db.flush()
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=hash_password(CLIENT_PASSWORD), full_name=full_name,
                        position=position, role="CLIENT", company_id=company.id)
            db.add(user)
        users[email] = user
    for email, full_name, position, role, password in STAFF:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=hash_password(password), full_name=full_name,
                        position=position, role=role)
            db.add(user)
        users[email] = user
    db.commit()
    return users


def _backdate(db, app: Application, days: int) -> None:
    shift = timedelta(days=days)
    for field in ("created_at", "updated_at", "submitted_at", "decided_at", "issued_at"):
        v = getattr(app, field)
        if v:
            setattr(app, field, v - shift)
    for ev in db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == app.id)):
        ev.created_at = ev.created_at - shift


class SeedIncomplete(RuntimeError):
    """Демо-история получилась не такой, как задумано (например, симулятор не ответил)."""


def wait_for_integrations(timeout_sec: float = 90) -> bool:
    """Ждём симулятор внешних источников: без него демо-заявки уйдут в ручной разбор без скоринга."""
    url = get_settings().integrations_url.rstrip("/") + "/health"
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=3).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


def wipe_history(db, app_ids: list[str]) -> None:
    """Удалить неудавшуюся демо-историю, чтобы следующий запуск сидера создал её заново."""
    if not app_ids:
        return
    for model in (ApplicationEvent, Document, InfoRequest, Job):
        db.execute(delete(model).where(model.application_id.in_(app_ids)))
    db.execute(delete(Application).where(Application.id.in_(app_ids)))
    db.commit()


def seed_history(db, users: dict[str, User], created: list[str] | None = None) -> None:
    if db.scalar(select(Application).limit(1)):
        return
    created = created if created is not None else []
    pipeline = Pipeline(db, step_delay=0)

    # 1. Пекарня: выданный год назад оборотный кредит — даёт «историю» и предодобренный овердрафт в кабинете
    bakery = users["bakery@demo.ru"]
    a = svc.create_draft(db, bakery, {"product_code": "WORKING_CAPITAL", "purpose": "inventory", "amount": 2_000_000,
                                      "term_months": 12, "revenue_last_year": 44_000_000,
                                      "revenue_prev_year": 41_000_000, "monthly_debt_payments": 80_000,
                                      "purpose_comment": "Закупка муки и упаковки к новогоднему сезону"}, None)
    created.append(a.id)
    svc.submit(db, bakery, a)
    db.commit()
    pipeline.process(a.id)
    db.refresh(a)
    if a.status in (Status.APPROVED.value, Status.COUNTER_OFFER.value):
        svc.accept_offer(db, bakery, a)
        db.commit()
        svc.sign(db, bakery, a, a.company.inn)
        db.commit()
        pipeline.disburse(a.id)
    db.refresh(a)
    if a.status != Status.ISSUED.value:
        raise SeedIncomplete(f"история пекарни: ожидали ISSUED, получили {a.status}")
    _backdate(db, a, 340)
    db.commit()
    log.info("seed_history bakery status=%s", a.status)

    # 2. IT-компания: крупная заявка ждёт аналитика — очередь не пустая с первой минуты
    it = users["it@demo.ru"]
    b = svc.create_draft(db, it, {"product_code": "WORKING_CAPITAL", "purpose": "contract", "amount": 20_000_000,
                                  "term_months": 24, "revenue_last_year": 140_000_000,
                                  "revenue_prev_year": 118_000_000, "monthly_debt_payments": 0,
                                  "purpose_comment": "Исполнение контракта на внедрение ERP для сети клиник"}, None)
    created.append(b.id)
    svc.add_document(db, it, b, "financial_statements", "otchetnost_2025.pdf", "application/pdf", FAKE_PDF, 10**7)
    svc.submit(db, it, b)
    db.commit()
    pipeline.process(b.id)
    db.refresh(b)
    if b.status != Status.MANUAL_REVIEW.value or not b.scoring:
        raise SeedIncomplete(f"заявка «Код и Цифры»: ожидали MANUAL_REVIEW со скорингом, получили {b.status}")
    _backdate(db, b, 0)
    db.commit()
    log.info("seed_history it status=%s", b.status)


def main() -> None:
    setup_logging()
    if not get_settings().seed_demo_data:
        log.info("seed_skipped")
        return
    with SessionLocal() as db:
        users = seed_users(db)
        if db.scalar(select(Application).limit(1)) is None and not wait_for_integrations():
            log.warning("seed_history_skipped reason=integrations_unavailable — история появится при следующем запуске")
        else:
            created: list[str] = []
            try:
                seed_history(db, users, created)
            except Exception:  # noqa: BLE001 — история не обязательна для запуска
                db.rollback()
                log.exception("seed_history_failed — удаляю неполную историю, она пересоздастся при следующем запуске")
                wipe_history(db, created)
    log.info("seed_done")


if __name__ == "__main__":
    main()
