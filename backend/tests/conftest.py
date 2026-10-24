"""Окружение API-тестов: SQLite, конвейер выполняется синхронно, внешние источники подменены."""
import os
import tempfile
from datetime import date, timedelta

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/test.db")
os.environ["PIPELINE_MODE"] = "inline"
os.environ["PIPELINE_STEP_DELAY_SEC"] = "0"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["LLM_URL"] = ""

import pytest  # noqa: E402

from app.integrations.gateway import CallInfo, IntegrationUnavailable, NotFoundInSource, set_gateway  # noqa: E402


def _reg(months: int) -> str:
    return (date.today() - timedelta(days=int(months * 30.44))).isoformat()


COMPANIES = {
    "7708123450": ({"status": "ACTIVE", "registration_date": _reg(103), "okved": "10.71", "director": {"disqualified": False}},
                   {"revenue": {"2025": 48_000_000, "2024": 41_000_000}, "tax_arrears": 0, "mass_address": False},
                   {"inquiries_30d": 1, "obligations": [{"monthly_payment": 80_000, "max_overdue_days_12m": 0, "current_overdue": 0}]}),
    "500100732259": ({"status": "ACTIVE", "registration_date": _reg(10), "okved": "56.30", "director": {"disqualified": False}},
                     {"revenue": {"2025": 9_600_000}, "tax_arrears": 0, "mass_address": False},
                     {"inquiries_30d": 3, "obligations": [{"monthly_payment": 25_000, "max_overdue_days_12m": 12, "current_overdue": 0}]}),
    "5027146895": ({"status": "ACTIVE", "registration_date": _reg(118), "okved": "49.41", "director": {"disqualified": False}},
                   {"revenue": {"2025": 62_000_000, "2024": 58_000_000}, "tax_arrears": 0, "mass_address": False},
                   {"inquiries_30d": 2, "obligations": [{"monthly_payment": 170_000, "max_overdue_days_12m": 0, "current_overdue": 0}]}),
    "7816039573": ({"status": "LIQUIDATING", "registration_date": _reg(150), "okved": "41.20", "director": {"disqualified": False}},
                   {"revenue": {"2025": 21_000_000, "2024": 35_000_000}, "tax_arrears": 420_000, "mass_address": False},
                   {"inquiries_30d": 6, "obligations": []}),
    "6623018470": ({"status": "ACTIVE", "registration_date": _reg(80), "okved": "01.11", "director": {"disqualified": False}},
                   {"revenue": {"2025": 18_000_000, "2024": 17_000_000}, "tax_arrears": 0, "mass_address": False},
                   {"inquiries_30d": 1, "obligations": [{"monthly_payment": 30_000, "max_overdue_days_12m": 0, "current_overdue": 0}]}),
    "2310045622": ({"status": "ACTIVE", "registration_date": _reg(92), "okved": "62.01", "director": {"disqualified": False}},
                   {"revenue": {"2025": 140_000_000, "2024": 118_000_000}, "tax_arrears": 0, "mass_address": False},
                   {"inquiries_30d": 0, "obligations": []}),
}


class FakeGateway:
    def __init__(self):
        self.down: set[str] = set()

    def _get(self, idx: int, source: str, inn: str):
        if source in self.down:
            raise IntegrationUnavailable(source, "нет ответа после 3 попыток")
        if inn not in COMPANIES:
            raise NotFoundInSource(source)
        return dict(COMPANIES[inn][idx]), CallInfo(source, 1, 5)

    def egrul(self, inn):
        return self._get(0, "egrul", inn)

    def fns(self, inn):
        return self._get(1, "fns", inn)

    def bki(self, inn):
        return self._get(2, "bki", inn)


@pytest.fixture(scope="session")
def _db():
    from app.db import Base, SessionLocal, engine
    from app.seed import seed_users
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_users(db)
    yield


@pytest.fixture()
def gateway(_db):
    gw = FakeGateway()
    set_gateway(gw)
    yield gw
    set_gateway(None)


@pytest.fixture()
def client(gateway):
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def login(client, email, password="demo12345") -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
