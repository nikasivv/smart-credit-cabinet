"""Сквозные сценарии через HTTP API. Соответствуют docs/test-scenarios.md."""
from tests.conftest import login

PDF = ("otchetnost.pdf", b"%PDF-1.4 test", "application/pdf")


def create(client, h, **fields):
    body = {"product_code": "WORKING_CAPITAL", "purpose": "inventory", "amount": 3_000_000, "term_months": 24,
            "revenue_last_year": 48_000_000, "revenue_prev_year": 41_000_000, "monthly_debt_payments": 80_000}
    body.update(fields)
    r = client.post("/api/applications", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def statuses(client, h, app_id):
    return [e["to_status"] for e in client.get(f"/api/applications/{app_id}/events", headers=h).json() if e["kind"] == "STATUS"]


def test_s1_happy_path_from_draft_to_money(client):
    h = login(client, "bakery@demo.ru")
    app = create(client, h)
    assert app["status"]["code"] == "DRAFT"
    r = client.post(f"/api/applications/{app['id']}/submit", headers=h)
    assert r.json()["status"]["code"] == "APPROVED", r.text
    assert r.json()["offer"]["amount"] == 3_000_000
    assert r.json()["score"]["grade"] == "A"
    assert client.post(f"/api/applications/{app['id']}/accept", headers=h).json()["status"]["code"] == "OFFER_ACCEPTED"
    bad = client.post(f"/api/applications/{app['id']}/sign", json={"confirmation_inn": "0000000000", "agree": True}, headers=h)
    assert bad.status_code == 422
    r = client.post(f"/api/applications/{app['id']}/sign", json={"confirmation_inn": "7708123450", "agree": True}, headers=h)
    assert r.json()["status"]["code"] == "ISSUED"
    assert statuses(client, h, app["id"]) == ["DRAFT", "SUBMITTED", "VALIDATION", "ENRICHMENT", "SCORING", "APPROVED",
                                              "OFFER_ACCEPTED", "SIGNED", "ISSUED"]


def test_s2_counter_offer_longer_term(client):
    h = login(client, "logistic@demo.ru")
    app = create(client, h, amount=5_000_000, term_months=12, revenue_last_year=62_000_000,
                 revenue_prev_year=58_000_000, monthly_debt_payments=170_000, purpose="contract")
    r = client.post(f"/api/applications/{app['id']}/submit", headers=h).json()
    assert r["status"]["code"] == "COUNTER_OFFER"
    assert r["offer"]["amount"] == 5_000_000 and r["offer"]["term_months"] > 12
    assert "limits" not in (r["decision"] or {}), "внутренние лимиты банка не показываются клиенту"


def test_s3_revenue_mismatch_requests_documents(client):
    h = login(client, "agro@demo.ru")
    app = create(client, h, amount=3_000_000, term_months=18, revenue_last_year=30_000_000,
                 revenue_prev_year=17_000_000, monthly_debt_payments=30_000)
    r = client.post(f"/api/applications/{app['id']}/submit", headers=h).json()
    assert r["status"]["code"] == "NEEDS_INFO"
    assert any(i["code"] == "revenue_mismatch" for i in r["info_request"]["items"])
    up = client.post(f"/api/applications/{app['id']}/documents", data={"doc_type": "financial_statements"},
                     files={"file": PDF}, headers=h)
    assert up.status_code == 201, up.text
    r = client.post(f"/api/applications/{app['id']}/info-response", json={"message": "Отчётность приложена"}, headers=h).json()
    assert r["status"]["code"] == "COUNTER_OFFER"
    assert r["offer"]["amount"] < 3_000_000


def test_s3b_investment_collateral_fixed_in_info_response(client):
    """Инвестиционный кредит: нет документов и залог ниже 70% суммы — клиент догружает документы и поднимает оценку."""
    h = login(client, "bakery@demo.ru")
    app = create(client, h, product_code="INVESTMENT", purpose="equipment", amount=1_100_000, term_months=12,
                 collateral_type="equipment", collateral_value=500_000)
    r = client.post(f"/api/applications/{app['id']}/submit", headers=h).json()
    assert r["status"]["code"] == "NEEDS_INFO"
    codes = {i["code"] for i in r["info_request"]["items"]}
    assert {"missing_document", "insufficient_collateral"} <= codes
    for doc in ("collateral_docs", "contract"):
        up = client.post(f"/api/applications/{app['id']}/documents", data={"doc_type": doc}, files={"file": PDF}, headers=h)
        assert up.status_code == 201, up.text
    r = client.post(f"/api/applications/{app['id']}/info-response",
                    json={"message": "Оценка уточнена", "collateral_value": 900_000}, headers=h).json()
    assert r["collateral_value"] == 900_000
    assert r["status"]["code"] not in ("NEEDS_INFO", "VALIDATION"), r["status"]


def test_s4_manual_review_and_analyst_decision(client):
    h = login(client, "coffee@demo.ru")
    app = create(client, h, product_code="EXPRESS", purpose="urgent", amount=1_500_000, term_months=18,
                 revenue_last_year=9_600_000, revenue_prev_year=None, monthly_debt_payments=25_000)
    r = client.post(f"/api/applications/{app['id']}/submit", headers=h).json()
    assert r["status"]["code"] == "MANUAL_REVIEW"
    assert r["score"] is None, "до решения специалиста клиент не видит скоринг"
    assert client.get("/api/analyst/queue", headers=h).status_code == 403

    a = login(client, "analyst@alfa.demo", "analyst12345")
    queue = client.get("/api/analyst/queue", headers=a).json()
    assert any(q["id"] == app["id"] for q in queue)
    card = client.get(f"/api/analyst/applications/{app['id']}", headers=a).json()
    assert card["scoring"]["grade"] == "D" and card["summary"]
    assert client.post(f"/api/analyst/applications/{app['id']}/assign", headers=a).status_code == 200
    a2 = login(client, "analyst2@alfa.demo", "analyst12345")
    assert client.post(f"/api/analyst/applications/{app['id']}/assign", headers=a2).status_code == 409
    d = client.post(f"/api/analyst/applications/{app['id']}/decision", headers=a,
                    json={"outcome": "APPROVED", "comment": "Одобряем меньшую сумму с учётом молодого бизнеса",
                          "amount": 800_000, "term_months": 18, "rate": 26.5})
    assert d.json()["status"] == "COUNTER_OFFER", "условия отличаются от запрошенных → встречное предложение"
    r = client.get(f"/api/applications/{app['id']}", headers=h).json()
    assert r["offer"]["amount"] == 800_000 and r["decision"]["decided_by"] == "specialist"


def test_s5_stop_factor_rejects(client):
    h = login(client, "build@demo.ru")
    app = create(client, h, amount=2_000_000, term_months=12, revenue_last_year=21_000_000, monthly_debt_payments=260_000)
    r = client.post(f"/api/applications/{app['id']}/submit", headers=h).json()
    assert r["status"]["code"] == "REJECTED"
    assert "ликвидации" in r["decision"]["client_explanation"]
    assert client.post(f"/api/applications/{app['id']}/accept", headers=h).status_code == 409


def test_s6_source_outage_degrades_to_manual_review(client, gateway):
    gateway.down.add("bki")
    h = login(client, "bakery@demo.ru")
    app = create(client, h)
    r = client.post(f"/api/applications/{app['id']}/submit", headers=h).json()
    assert r["status"]["code"] == "MANUAL_REVIEW"


def test_object_level_access(client):
    owner = login(client, "bakery@demo.ru")
    app = create(client, owner)
    stranger = login(client, "logistic@demo.ru")
    assert client.get(f"/api/applications/{app['id']}", headers=stranger).status_code == 404
    assert client.post(f"/api/applications/{app['id']}/submit", headers=stranger).status_code == 404
    assert client.get("/api/applications").status_code == 401


def test_idempotency_and_double_submit(client):
    h = login(client, "bakery@demo.ru")
    body = {"product_code": "OVERDRAFT", "purpose": "cash_gap", "amount": 500_000, "term_months": 6,
            "revenue_last_year": 48_000_000, "monthly_debt_payments": 80_000}
    k = {**h, "Idempotency-Key": "test-key-123"}
    a = client.post("/api/applications", json=body, headers=k).json()
    b = client.post("/api/applications", json=body, headers=k).json()
    assert a["id"] == b["id"]
    first = client.post(f"/api/applications/{a['id']}/submit", headers=h).json()
    second = client.post(f"/api/applications/{a['id']}/submit", headers=h)
    assert second.status_code == 200 and second.json()["status"]["code"] == first["status"]["code"]
    assert statuses(client, h, a["id"]).count("SUBMITTED") == 1


def test_validation_errors_are_field_level(client):
    h = login(client, "bakery@demo.ru")
    app = create(client, h, product_code="EXPRESS", amount=9_000_000, term_months=48)
    r = client.post(f"/api/applications/{app['id']}/submit", headers=h)
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["details"]}
    assert {"amount", "term_months"} <= fields


def test_implausible_figures_rejected_on_save(client):
    """Выручка «13 ₽» и платежи больше выручки — ошибка сразу при сохранении шага, а не дозапрос банка."""
    h = login(client, "bakery@demo.ru")
    body = {"product_code": "WORKING_CAPITAL", "purpose": "inventory", "amount": 1_100_000, "term_months": 12,
            "revenue_last_year": 13, "monthly_debt_payments": 122_121_122}
    r = client.post("/api/applications", json=body, headers=h)
    assert r.status_code == 422
    assert {d["field"] for d in r.json()["details"]} == {"revenue_last_year"}
    app = create(client, h)
    r = client.patch(f"/api/applications/{app['id']}", headers=h,
                     json={"monthly_debt_payments": 122_121_122, "version": app["version"]})
    assert r.status_code == 422
    assert r.json()["details"][0]["field"] == "monthly_debt_payments"
    assert "больше выручки" in r.json()["details"][0]["message"]
    # Черновик не изменился
    assert client.get(f"/api/applications/{app['id']}", headers=h).json()["monthly_debt_payments"] == 80_000


def test_client_deletes_wrong_document(client):
    """Ошибочно загруженный файл можно убрать в черновике; после отправки — нельзя; чужой — не найти."""
    h = login(client, "bakery@demo.ru")
    app = create(client, h)
    doc = client.post(f"/api/applications/{app['id']}/documents", data={"doc_type": "contract"}, files={"file": PDF}, headers=h).json()
    other = login(client, "logistic@demo.ru")
    assert client.delete(f"/api/applications/{app['id']}/documents/{doc['id']}", headers=other).status_code == 404
    assert client.delete(f"/api/applications/{app['id']}/documents/{doc['id']}", headers=h).status_code == 204
    a = client.get(f"/api/applications/{app['id']}", headers=h).json()
    assert a["documents"] == []
    events = [e["message"] for e in client.get(f"/api/applications/{app['id']}/events", headers=h).json()]
    assert "Удалён документ: Договор или спецификация на покупку" in events
    assert client.delete(f"/api/applications/{app['id']}/documents/{doc['id']}", headers=h).status_code == 404
    # После отправки банк уже рассматривает заявку — документ не удалить
    doc2 = client.post(f"/api/applications/{app['id']}/documents", data={"doc_type": "contract"}, files={"file": PDF}, headers=h).json()
    client.post(f"/api/applications/{app['id']}/submit", headers=h)
    r = client.delete(f"/api/applications/{app['id']}/documents/{doc2['id']}", headers=h)
    assert r.status_code == 409


def test_draft_optimistic_lock(client):
    h = login(client, "bakery@demo.ru")
    app = create(client, h)
    ok = client.patch(f"/api/applications/{app['id']}", json={"amount": 2_500_000, "version": app["version"]}, headers=h)
    assert ok.status_code == 200
    stale = client.patch(f"/api/applications/{app['id']}", json={"amount": 2_000_000, "version": app["version"]}, headers=h)
    assert stale.status_code == 409


def test_feed_shows_actions_events_and_tips(client):
    """Блок «Ваши заявки и предложения»: действия по заявкам сверху, советы по форме бизнеса, без общих новостей."""
    h = login(client, "logistic@demo.ru")
    draft = client.post("/api/applications", json={"product_code": "WORKING_CAPITAL", "purpose": "inventory",
                                                   "amount": 1_000_000, "term_months": 12}, headers=h).json()
    feed = client.get("/api/feed", headers=h).json()
    kinds = [i["kind"] for i in feed["items"]]
    assert kinds[0] == "action" and feed["items"][0]["application_id"] == draft["id"]
    assert set(kinds) <= {"action", "offer", "event", "tip"}
    ooo_tips = {i["id"] for i in feed["items"] if i["kind"] == "tip"}
    ip_tips = {i["id"] for i in client.get("/api/feed", headers=login(client, "coffee@demo.ru")).json()["items"]
               if i["kind"] == "tip"}
    assert "tip-large-amount" in ooo_tips and "tip-ip-revenue" in ip_tips
    assert all(i["reason"] for i in feed["items"])


def test_catalog_calculator_and_suggest(client):
    h = login(client, "bakery@demo.ru")
    assert len(client.get("/api/catalog").json()["products"]) == 4
    c = client.post("/api/calculator", json={"product_code": "WORKING_CAPITAL", "amount": 1_000_000, "term_months": 12}).json()
    assert c["monthly_payment_from"] > 0
    s = client.post("/api/assistant/suggest", json={"text": "нужно купить печь, около 2 млн"}, headers=h).json()
    assert s["source"] == "rules" and s["purpose"] == "equipment"
    assert s["recommendations"][0]["product_code"] == "EXPRESS"


def test_health(client):
    assert client.get("/health/ready").json()["db"] == "ok"


def test_validation_messages_in_russian(client):
    h = login(client, "agro@demo.ru")
    r = client.post("/api/applications", headers=h, json={
        "product_code": "WORKING_CAPITAL", "purpose": "inventory", "amount": 1_000_000, "term_months": 12,
        "revenue_prev_year": 9_877_777_777_777_776_000_000_000_000_000_000, "term_months_extra": "x"})
    assert r.status_code == 422
    body = r.json()
    assert body["message"] == "Проверьте введённые данные"
    msgs = {d["field"]: d["message"] for d in body["details"]}
    assert msgs["revenue_prev_year"] == "Не больше 100 000 000 000"
    r = client.post("/api/applications", headers=h, json={"product_code": "WORKING_CAPITAL", "purpose": "inventory",
                                                          "amount": "много", "term_months": 12})
    assert {d["field"]: d["message"] for d in r.json()["details"]}["amount"] == "Введите целое число"


def test_risk_manager_policy_and_audit(client):
    """Риск-менеджер видит политику и аудит с контекстом, но не может принимать решения; клиенту это закрыто."""
    hc = login(client, "bakery@demo.ru")
    a = client.post("/api/applications", headers=hc, json={
        "product_code": "WORKING_CAPITAL", "purpose": "inventory", "amount": 3_000_000, "term_months": 24,
        "revenue_last_year": 48_000_000, "revenue_prev_year": 41_000_000, "monthly_debt_payments": 80_000}).json()
    client.post(f"/api/applications/{a['id']}/submit", headers=hc)

    hr = login(client, "risk@alfa.demo", "risk12345")
    pol = client.get("/api/admin/policy", headers=hr).json()
    assert pol["auto_decision_limit"] == 15_000_000 and pol["min_dscr"] == 1.25
    assert pol["products"]["WORKING_CAPITAL"]["name"] and pol["industry_risk"]["10"]["margin"] > 0

    audit = client.get("/api/admin/audit?limit=50", headers=hr).json()
    mine = [e for e in audit if e["application_id"] == a["id"]]
    assert mine and all(e["company_name"] == "ООО «Северная пекарня»" and e["application_number"] for e in mine)
    assert any(e["actor_type"] == "CLIENT" and e["actor_name"] for e in mine)
    hidden = client.get("/api/admin/audit?hidden_only=true", headers=hr).json()
    assert all(not e["visible_to_client"] for e in hidden)

    assert client.post(f"/api/analyst/applications/{a['id']}/assign", headers=hr).status_code == 403
    assert client.get("/api/admin/audit", headers=hc).status_code == 403