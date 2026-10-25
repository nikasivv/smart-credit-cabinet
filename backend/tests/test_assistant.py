"""Ассистент подбора: ответ языковой модели проверяется правилами и не может навязать выдуманное."""
import pytest

from app.domain.recommend import amount_from_text, mentions_amount, purpose_from_text, term_from_text
from app.services import assistant


@pytest.mark.parametrize("text, amount", [
    ("нужно закупить муку к сезону, примерно 3 млн", 3_000_000),
    ("около 2,5 миллиона на печь", 2_500_000),
    ("800 тыс. на зарплаты", 800_000),
    ("поставщикам надо платить сейчас, тысяч 800", 800_000),
    ("около полутора миллионов на ремонт", 1_500_000),
    ("надо обновить парк, взять два фургона", None),
])
def test_amount_from_text(text, amount):
    assert amount_from_text(text) == amount


@pytest.mark.parametrize("text,term", [
    ("2,5 млн на 2 года", 24), ("на 18 месяцев", 18), ("кредит на 3 года", 36), ("лет на 5", None),
    ("нужно на полгода", 6), ("полтора года", 18), ("деньги на год", 12), ("выручка за 2025 год 40 млн", None),
    ("примерно 2,5 млн", None), ("на 6 мес.", 6),
])
def test_term_from_text(text, term):
    assert term_from_text(text) == term


def test_rules_return_term_without_llm(monkeypatch):
    monkeypatch.setattr(assistant, "llm_available", lambda: False)
    r = assistant.suggest("нужно закупить муку к сезону, примерно 2,5 млн на 2 года", None, None)
    assert (r["purpose"], r["amount"], r["term_months"]) == ("inventory", 2_500_000, 24)


def test_vans_are_equipment():
    assert purpose_from_text("надо обновить парк, взять два фургона") == "equipment"
    assert not mentions_amount("надо обновить парк, взять два фургона")


@pytest.fixture()
def fake_llm(monkeypatch):
    def use(answer):
        monkeypatch.setattr(assistant, "llm_available", lambda: True)
        monkeypatch.setattr(assistant, "_llm_extract", lambda text: answer)
    return use


def test_llm_hallucination_is_corrected(fake_llm):
    # Реальный случай: модель ответила «открыть точку, 200 тыс.» на фразу про фургоны без суммы
    fake_llm({"purpose": "expansion", "amount": 200_000, "term_months": 24})
    r = assistant.suggest("надо обновить парк, взять два фургона", None, None)
    assert r["purpose"] == "equipment"
    assert r["amount"] is None and r["term_months"] is None
    assert r["source"] == "rules"


def test_llm_used_when_rules_find_nothing(fake_llm):
    fake_llm({"purpose": "cash_gap", "amount": 600_000, "term_months": 6})
    r = assistant.suggest("покупатели рассчитываются через два месяца, а платить надо сегодня, 600 тыс на полгода", None, None)
    assert r["source"] == "llm" and r["purpose"] == "cash_gap"
    assert r["amount"] == 600_000


def test_rule_amount_beats_llm_amount(fake_llm):
    fake_llm({"purpose": "inventory", "amount": 30_000_000, "term_months": None})
    r = assistant.suggest("закупить сырьё к сезону, 3 млн", None, None)
    assert r["purpose"] == "inventory" and r["amount"] == 3_000_000