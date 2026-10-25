"""Тесты доменной логики. Не требуют БД и сети."""
from app.domain.policy import annuity_payment, decide, max_amount_for_payment
from app.domain.products import PRODUCTS, required_documents
from app.domain.recommend import amount_from_text, purpose_from_text, recommend
from app.domain.scoring import ScoringInput, score
from app.domain.state_machine import (TransitionError, all_statuses_reachable, allowed_targets,
                                      check_transition)
from app.domain.statuses import STATUS_INFO, Actor, Status
from app.domain.validation import (ApplicationData, completeness_check, inn_is_valid,
                                   revenue_discrepancy, sanity_check, validate_for_submit)


def make_input(**kw) -> ScoringInput:
    base = dict(legal_status="ACTIVE", business_age_months=100, okved="10.71", revenue_last=48_000_000,
                revenue_prev=41_000_000, existing_monthly_payments=80_000, max_overdue_days_12m=0,
                current_overdue_amount=0, inquiries_30d=1, tax_arrears=0, mass_address=False,
                director_disqualified=False)
    base.update(kw)
    return ScoringInput(**base)


# ---------- машина состояний ----------

def test_every_status_has_client_description():
    assert set(STATUS_INFO) == set(Status)


def test_all_statuses_reachable_from_draft():
    assert all_statuses_reachable()


def test_client_cannot_approve_own_application():
    try:
        check_transition(Status.MANUAL_REVIEW, Status.APPROVED, Actor.CLIENT)
    except TransitionError:
        return
    raise AssertionError("клиент не должен одобрять заявку")


def test_terminal_status_is_final():
    for actor in Actor:
        assert allowed_targets(Status.ISSUED, actor) == []
    try:
        check_transition(Status.REJECTED, Status.APPROVED, Actor.ANALYST)
    except TransitionError as e:
        assert "финальном" in str(e)
    else:
        raise AssertionError


def test_analyst_can_request_info():
    check_transition(Status.MANUAL_REVIEW, Status.NEEDS_INFO, Actor.ANALYST)


# ---------- валидация ----------

def test_inn_checksum():
    for good in ("7708123450", "500100732259", "5027146895", "7816039573", "6623018470"):
        assert inn_is_valid(good), good
    for bad in ("7708123451", "123", "abcdefghij", "500100732258"):
        assert not inn_is_valid(bad), bad


def test_submit_validation_checks_product_ranges():
    p = PRODUCTS["EXPRESS"]
    data = ApplicationData("EXPRESS", amount=9_000_000, term_months=48, purpose="urgent",
                           revenue_last_year=10_000_000, revenue_prev_year=None, monthly_debt_payments=0)
    codes = {(i.field, i.code) for i in validate_for_submit(data, p)}
    assert ("amount", "out_of_range") in codes and ("term_months", "out_of_range") in codes


def test_sanity_catches_typos_in_figures():
    def codes(**kw):
        base = dict(product_code="WORKING_CAPITAL", amount=1_100_000, term_months=12, purpose="new_point",
                    revenue_last_year=48_000_000, revenue_prev_year=41_000_000, monthly_debt_payments=80_000)
        base.update(kw)
        return {(i.field, i.code) for i in sanity_check(ApplicationData(**base))}
    assert codes() == set()
    assert ("revenue_last_year", "implausible") in codes(revenue_last_year=13)              # ввели в миллионах
    assert ("revenue_prev_year", "implausible") in codes(revenue_prev_year=41_000)
    assert codes(revenue_prev_year=0) == set()                                               # новый бизнес — можно 0
    assert ("monthly_debt_payments", "exceeds_revenue") in codes(monthly_debt_payments=122_121_122)
    assert codes(revenue_last_year=None, monthly_debt_payments=None) == set()               # пустое — не сюда
    # При отправке опечатка тоже блокирует, и поле не дублируется ошибкой «обязательно»
    data = ApplicationData("WORKING_CAPITAL", 1_100_000, 12, "inventory", 13, None, 0)
    issues = [i for i in validate_for_submit(data, PRODUCTS["WORKING_CAPITAL"]) if i.field == "revenue_last_year"]
    assert [i.code for i in issues] == ["implausible"]


def test_investment_requires_collateral_and_documents():
    p = PRODUCTS["INVESTMENT"]
    data = ApplicationData("INVESTMENT", 10_000_000, 60, "equipment", 80_000_000, 70_000_000, 0)
    assert {i.field for i in validate_for_submit(data, p)} >= {"collateral_type", "collateral_value"}
    data.collateral_type, data.collateral_value = "equipment", 5_000_000
    fields = {i.field for i in completeness_check(data, p)}
    assert "documents.collateral_docs" in fields
    assert "documents.financial_statements" in fields      # сумма > 5 млн
    assert "collateral_value" in fields                    # залог < 70% суммы


def test_required_docs_depend_on_amount():
    assert required_documents(PRODUCTS["WORKING_CAPITAL"], 3_000_000) == []
    assert required_documents(PRODUCTS["WORKING_CAPITAL"], 6_000_000) == ["financial_statements"]


def test_revenue_discrepancy():
    assert revenue_discrepancy(30_000_000, 18_000_000)
    assert not revenue_discrepancy(20_000_000, 18_000_000)
    assert not revenue_discrepancy(30_000_000, None)


# ---------- финансовая математика ----------

def test_annuity_roundtrip():
    pay = annuity_payment(1_000_000, 20.0, 12)
    assert 92_000 < pay < 93_000
    assert abs(max_amount_for_payment(pay, 20.0, 12) - 1_000_000) < 200


# ---------- скоринг ----------

def test_strong_company_gets_grade_a():
    s = score(make_input())
    assert s.grade == "A" and not s.stop_factors
    assert s.score == 600 + sum(f.points for f in s.factors)


def test_liquidation_is_stop_factor():
    s = score(make_input(legal_status="LIQUIDATING"))
    assert [x.code for x in s.stop_factors] == ["liquidation"]


def test_overdue_lowers_score():
    good, bad = score(make_input()), score(make_input(max_overdue_days_12m=45))
    assert bad.score < good.score


# ---------- кредитное решение по демо-персонам ----------

def test_bakery_auto_approved():
    inp = make_input()
    d = decide(PRODUCTS["WORKING_CAPITAL"], 3_000_000, 24, score(inp), inp)
    assert d.outcome == Status.APPROVED
    assert d.offer.amount == 3_000_000 and d.offer.rate == 19.5


def test_logistics_counter_offer_longer_term():
    inp = make_input(okved="49.41", revenue_last=62_000_000, revenue_prev=58_000_000,
                     existing_monthly_payments=170_000, inquiries_30d=2)
    d = decide(PRODUCTS["WORKING_CAPITAL"], 5_000_000, 12, score(inp), inp)
    assert d.outcome == Status.COUNTER_OFFER
    assert d.offer.amount == 5_000_000 and d.offer.term_months > 12


def test_agro_counter_offer_reduced_amount():
    inp = make_input(okved="01.11", revenue_last=18_000_000, revenue_prev=17_000_000,
                     existing_monthly_payments=30_000)
    d = decide(PRODUCTS["WORKING_CAPITAL"], 3_000_000, 18, score(inp), inp)
    assert d.outcome == Status.COUNTER_OFFER
    assert d.offer.amount < 3_000_000


def test_coffee_goes_to_manual_review():
    inp = make_input(business_age_months=10, okved="56.30", revenue_last=9_600_000, revenue_prev=None,
                     existing_monthly_payments=25_000, max_overdue_days_12m=12, inquiries_30d=3)
    s = score(inp)
    assert s.grade == "D"
    d = decide(PRODUCTS["EXPRESS"], 1_500_000, 18, s, inp)
    assert d.outcome == Status.MANUAL_REVIEW
    assert d.recommended_outcome in (Status.COUNTER_OFFER, Status.APPROVED)


def test_liquidating_company_rejected():
    inp = make_input(legal_status="LIQUIDATING", okved="41.20")
    d = decide(PRODUCTS["WORKING_CAPITAL"], 2_000_000, 12, score(inp), inp)
    assert d.outcome == Status.REJECTED and "ликвидации" in d.client_explanation


def test_large_amount_requires_manual_review():
    inp = make_input(revenue_last=400_000_000, revenue_prev=380_000_000)
    d = decide(PRODUCTS["WORKING_CAPITAL"], 20_000_000, 36, score(inp), inp)
    assert d.outcome == Status.MANUAL_REVIEW


def test_same_score_different_product_terms():
    inp = make_input()
    s = score(inp)
    a = decide(PRODUCTS["WORKING_CAPITAL"], 1_000_000, 12, s, inp)
    b = decide(PRODUCTS["EXPRESS"], 1_000_000, 12, s, inp)
    assert a.offer.rate != b.offer.rate


# ---------- подбор продукта ----------

def test_recommendation_by_purpose_and_amount():
    assert recommend("cash_gap")[0].product_code == "OVERDRAFT"
    assert recommend("equipment", 2_000_000)[0].product_code == "EXPRESS"
    assert recommend("equipment", 20_000_000)[0].product_code == "INVESTMENT"


def test_purpose_and_amount_from_free_text():
    t = "Нужно купить новую печь для пекарни, примерно 2,5 млн"
    assert purpose_from_text(t) == "equipment"
    assert amount_from_text(t) == 2_500_000