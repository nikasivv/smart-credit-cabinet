import json
from pathlib import Path

from app.domain.feed import Profile, rank_tips

TIPS = json.loads((Path(__file__).parent.parent / "app" / "data" / "tips.json").read_text(encoding="utf-8"))


def test_tips_filtered_by_legal_form():
    ip = {t["id"] for t in rank_tips(TIPS, Profile("IP", set()), limit=10)}
    ooo = {t["id"] for t in rank_tips(TIPS, Profile("OOO", set()), limit=10)}
    assert "tip-ip-revenue" in ip and "tip-ip-revenue" not in ooo
    assert "tip-large-amount" in ooo and "tip-large-amount" not in ip


def test_product_tip_ranked_first_with_reason():
    items = rank_tips(TIPS, Profile("OOO", {"OVERDRAFT"}))
    assert items[0]["id"] == "tip-overdraft-vs-loan"
    assert items[0]["reason"] == "Связано с вашей заявкой или предложением банка"
    assert len(items) <= 3 and all(i["reason"] for i in items)


def test_only_tips_no_general_news():
    assert {t["kind"] for t in TIPS} == {"tip"}
