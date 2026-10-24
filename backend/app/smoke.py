"""Быстрая сквозная проверка запущенного стенда (≈15 секунд).

    docker compose exec api python -m app.smoke

Проходит путь «Северной пекарни»: заявка → автоматическое одобрение →
принятие условий → подпись → зачисление, и сценарий ручного рассмотрения
с решением аналитика. Использует только публичный API.
"""
from __future__ import annotations

import os
import sys
import time

import httpx

API = os.getenv("SMOKE_API_URL", "http://localhost:8000")


def step(msg: str) -> None:
    print(f"  ✓ {msg}", flush=True)


def wait_status(c: httpx.Client, h: dict, app_id: str, targets: set[str], timeout: float = 40) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        a = c.get(f"/api/applications/{app_id}", headers=h).json()
        if a["status"]["code"] in targets:
            return a
        time.sleep(0.5)
    raise SystemExit(f"Статус не дошёл до {targets}, последний: {a['status']['code']}")


def login(c: httpx.Client, email: str, password: str) -> dict:
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main() -> int:
    with httpx.Client(base_url=API, timeout=10) as c:
        print("Сценарий 1. Автоматическое одобрение и выдача")
        h = login(c, "bakery@demo.ru", "demo12345")
        a = c.post("/api/applications", headers=h, json={
            "product_code": "WORKING_CAPITAL", "purpose": "inventory", "amount": 3_000_000, "term_months": 24,
            "revenue_last_year": 48_000_000, "revenue_prev_year": 41_000_000, "monthly_debt_payments": 80_000}).json()
        step(f"черновик {a['number']} создан")
        c.post(f"/api/applications/{a['id']}/submit", headers=h).raise_for_status()
        step("заявка отправлена, ждём конвейер")
        a = wait_status(c, h, a["id"], {"APPROVED", "COUNTER_OFFER", "REJECTED", "MANUAL_REVIEW"})
        assert a["status"]["code"] == "APPROVED", a["status"]
        amount = f"{a['offer']['amount']:,}".replace(",", " ")
        step(f"решение: {a['status']['title']}, {amount} ₽ под {a['offer']['rate']}%")
        c.post(f"/api/applications/{a['id']}/accept", headers=h).raise_for_status()
        c.post(f"/api/applications/{a['id']}/sign", headers=h, json={"confirmation_inn": "7708123450", "agree": True}).raise_for_status()
        step("условия приняты, договор подписан")
        a = wait_status(c, h, a["id"], {"ISSUED"})
        step("деньги зачислены")

        print("Сценарий 2. Ручное рассмотрение")
        hc = login(c, "coffee@demo.ru", "demo12345")
        b = c.post("/api/applications", headers=hc, json={
            "product_code": "EXPRESS", "purpose": "urgent", "amount": 1_500_000, "term_months": 18,
            "revenue_last_year": 9_600_000, "monthly_debt_payments": 25_000}).json()
        c.post(f"/api/applications/{b['id']}/submit", headers=hc).raise_for_status()
        b = wait_status(c, hc, b["id"], {"MANUAL_REVIEW", "APPROVED", "COUNTER_OFFER", "REJECTED"})
        assert b["status"]["code"] == "MANUAL_REVIEW", b["status"]
        step("заявка ушла специалисту")
        ha = login(c, "analyst@alfa.demo", "analyst12345")
        c.post(f"/api/analyst/applications/{b['id']}/decision", headers=ha, json={
            "outcome": "COUNTER_OFFER", "comment": "Готовы выдать 800 тыс. ₽ с учётом возраста бизнеса",
            "amount": 800_000, "term_months": 18, "rate": 26.5}).raise_for_status()
        b = wait_status(c, hc, b["id"], {"COUNTER_OFFER"})
        step("аналитик сделал встречное предложение — клиент его видит")
    print("Готово: все шаги пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
