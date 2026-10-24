"""Симулятор внешних источников данных.

Контракты упрощены, но сохраняют смысл реальных интеграций:
* GET /egrul/{inn}                     — ЕГРЮЛ/ЕГРИП: статус, регистрация, ОКВЭД, руководитель
* GET /fns/transparent-business/{inn}  — ФНС «Прозрачный бизнес»: выручка, недоимка, массовый адрес
* GET /bki/{inn}/report                — бюро кредитных историй: обязательства, просрочки, запросы

Демо-компании берутся из data/companies.json. Для любого другого
корректного ИНН данные генерируются детерминированно (одинаковые
при каждом запросе), чтобы можно было проверить конвейер на новых клиентах.

POST /_admin/chaos — включить сбои и задержки, чтобы показать
отказоустойчивость конвейера (retry, circuit breaker, деградация в ручной разбор).
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Симулятор внешних источников (ЕГРЮЛ, ФНС, БКИ)", version="1.0.0")
DATA: dict = json.loads((Path(__file__).parent / "data" / "companies.json").read_text(encoding="utf-8"))


class Chaos(BaseModel):
    fail_rate: float = Field(0.0, ge=0, le=1, description="Доля запросов, на которые вернётся 503")
    latency_ms: int = Field(0, ge=0, le=10_000)
    sources: list[str] = Field(default_factory=lambda: ["egrul", "fns", "bki"])


chaos = Chaos()


def inn_is_valid(inn: str) -> bool:
    if not inn.isdigit() or len(inn) not in (10, 12):
        return False
    d = [int(c) for c in inn]

    def check(coeffs):
        return sum(x * k for x, k in zip(d, coeffs)) % 11 % 10

    if len(inn) == 10:
        return check([2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[9]
    return check([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[10] and check([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[11]


def _apply_chaos(source: str) -> None:
    if source not in chaos.sources:
        return
    if chaos.latency_ms:
        time.sleep(chaos.latency_ms / 1000)
    if chaos.fail_rate and random.random() < chaos.fail_rate:
        raise HTTPException(503, detail=f"{source}: сервис временно недоступен (симуляция)")


def _generated(inn: str) -> dict:
    rnd = random.Random(int(hashlib.sha256(inn.encode()).hexdigest(), 16))
    revenue = rnd.randrange(5, 120) * 1_000_000
    ip = len(inn) == 12
    okved, okved_name = rnd.choice([("47.11", "Розничная торговля"), ("62.01", "Разработка ПО"),
                                    ("10.71", "Производство хлеба"), ("49.41", "Грузоперевозки"),
                                    ("56.10", "Деятельность ресторанов")])
    return {
        "persona": "Сгенерировано по ИНН",
        "egrul": {"name": f"{'ИП' if ip else 'ООО'} «Компания {inn[-4:]}»", "legal_form": "IP" if ip else "OOO",
                  "ogrn": str(rnd.randrange(10**12, 10**13)), "status": "ACTIVE",
                  "registered_months_ago": rnd.randrange(4, 160), "okved": okved, "okved_name": okved_name,
                  "region": "Москва", "address": "г. Москва", "director": {"name": "Иванов Иван Иванович",
                                                                          "disqualified": False}, "founders": []},
        "fns": {"revenue": {"2025": revenue, "2024": int(revenue * rnd.uniform(0.7, 1.2))},
                "tax_arrears": 0, "mass_address": rnd.random() < 0.1, "employees": rnd.randrange(2, 80),
                "tax_regime": "УСН 6%" if ip else "ОСН"},
        "bki": {"inquiries_30d": rnd.randrange(0, 4), "obligations": [
            {"creditor": "Банк «Пример»", "type": "Кредит", "amount": revenue // 10, "balance": revenue // 20,
             "monthly_payment": revenue // 300, "max_overdue_days_12m": rnd.choice([0, 0, 0, 5, 20]),
             "current_overdue": 0}]},
    }


def _company(inn: str) -> dict:
    if not inn_is_valid(inn):
        raise HTTPException(404, detail="Компания с таким ИНН не найдена")
    return DATA.get(inn) or _generated(inn)


@app.get("/egrul/{inn}", tags=["ЕГРЮЛ/ЕГРИП"])
def egrul(inn: str):
    _apply_chaos("egrul")
    e = dict(_company(inn)["egrul"])
    e["registration_date"] = (date.today() - timedelta(days=int(e.pop("registered_months_ago") * 30.44))).isoformat()
    return {"inn": inn, **e, "source": "egrul-simulator", "as_of": date.today().isoformat()}


@app.get("/fns/transparent-business/{inn}", tags=["ФНС"])
def fns(inn: str):
    _apply_chaos("fns")
    return {"inn": inn, **_company(inn)["fns"], "source": "fns-simulator", "as_of": date.today().isoformat()}


@app.get("/bki/{inn}/report", tags=["БКИ"])
def bki(inn: str):
    _apply_chaos("bki")
    b = _company(inn)["bki"]
    return {"inn": inn, "report_date": date.today().isoformat(), **b, "source": "bki-simulator"}


@app.get("/_admin/chaos", tags=["Симуляция сбоев"])
def get_chaos():
    return chaos


@app.post("/_admin/chaos", tags=["Симуляция сбоев"])
def set_chaos(c: Chaos):
    global chaos
    chaos = c
    return chaos


@app.get("/_admin/companies", tags=["Симуляция сбоев"])
def demo_companies():
    return [{"inn": k, "name": v["egrul"]["name"], "persona": v["persona"]} for k, v in DATA.items()]


@app.get("/health")
def health():
    return {"status": "ok"}
