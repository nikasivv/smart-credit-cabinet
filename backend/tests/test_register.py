"""Регистрация клиента по ИНН: реквизиты из ЕГРЮЛ/ЕГРИП, сразу вход, понятные ошибки по-русски."""
from tests import conftest

NEW_INN = "5003001259"          # синтетический корректный ИНН, которого нет среди демо-компаний
NEW_IP_INN = "500100732259"     # ИНН ИП Смирновой — уже подключена через сидер


def _form(**over):
    body = {"inn": NEW_INN, "full_name": "Мария  Петрова", "position": "Генеральный директор",
            "email": "Maria@Example.ru", "password": "secret-123"}
    body.update(over)
    return body


def _add_company(monkeypatch, inn=NEW_INN, **egrul):
    data = ({"status": "ACTIVE", "registration_date": "2020-01-01", "okved": "47.11", "okved_name": "Розничная торговля",
             "name": "ООО «Новая лавка»", "legal_form": "OOO", "region": "Москва", "director": {"disqualified": False},
             **egrul}, {"revenue": {"2025": 20_000_000}, "tax_arrears": 0, "mass_address": False},
            {"inquiries_30d": 0, "obligations": []})
    monkeypatch.setitem(conftest.COMPANIES, inn, data)


def test_register_creates_company_from_registry_and_logs_in(client, monkeypatch):
    _add_company(monkeypatch)
    r = client.post("/api/auth/register", json=_form())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["email"] == "maria@example.ru" and body["user"]["full_name"] == "Мария Петрова"
    assert body["user"]["role"] == "CLIENT"
    company = body["user"]["company"]
    assert company["name"] == "ООО «Новая лавка»" and company["inn"] == NEW_INN and company["okved"] == "47.11"
    h = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get("/api/auth/me", headers=h).json()["email"] == "maria@example.ru"
    # Тем же паролем можно войти обычным способом
    assert client.post("/api/auth/login", json={"email": "maria@example.ru", "password": "secret-123"}).status_code == 200

    again = client.post("/api/auth/register", json=_form(email="other@example.ru"))
    assert again.status_code == 409 and again.json()["code"] == "company_taken"
    dup = client.post("/api/auth/register", json=_form(inn="7705008121", email="maria@example.ru"))
    assert dup.status_code == 409 and dup.json()["code"] == "email_taken"


def test_register_rejects_demo_company_and_bad_input(client):
    taken = client.post("/api/auth/register", json=_form(inn=NEW_IP_INN, email="x1@example.ru"))
    assert taken.status_code == 409
    bad = client.post("/api/auth/register", json=_form(inn="1234567890", email="bad-email", password="123"))
    assert bad.status_code == 422
    msgs = {d["field"]: d["message"] for d in bad.json()["details"]}
    assert msgs["inn"].startswith("Проверьте ИНН")
    assert msgs["email"] == "Проверьте email"
    assert msgs["password"] == "Минимум 8 символов"


def test_register_registry_not_found_and_unavailable(client, gateway):
    nf = client.post("/api/auth/register", json=_form(inn="6311004584", email="nf@example.ru"))
    assert nf.status_code == 422
    assert nf.json()["details"][0] == {"field": "inn", "message": "Компании с таким ИНН нет в ЕГРЮЛ/ЕГРИП"}
    gateway.down = {"egrul"}
    down = client.post("/api/auth/register", json=_form(inn="7705008121", email="down@example.ru"))
    assert down.status_code == 503 and "не отвечает" in down.json()["message"]