"""Ассистент подбора продукта.

Задача, которую решает ИИ: клиент описывает потребность своими словами
(«нужна новая печь, тысяч 800, деньги верну за год»), а система
переводит это в цель и сумму и подбирает продукт.

Ответственность разделена:
* LLM (открытые веса, локально через Ollama) — только извлекает цель и сумму из текста;
* правила домена — подбирают продукт и формулируют объяснение.
Ответ LLM проверяется по справочнику целей; при недоступности модели,
таймауте или невалидном ответе используется разбор по ключевым словам.
Кредитное решение ИИ не принимает.
"""
from __future__ import annotations

import json
import logging
import re
import time

import httpx

from ..config import get_settings
from ..domain.products import PRODUCTS, PURPOSES
from ..domain.recommend import (amount_from_text, mentions_amount, purpose_from_text, purpose_scores, recommend,
                               term_from_text)

log = logging.getLogger("scc.assistant")
_status_cache: dict[str, tuple[float, bool]] = {}

SYSTEM_PROMPT = (
    "Ты помогаешь предпринимателю выбрать цель кредита. Ответь ТОЛЬКО JSON-объектом "
    '{"purpose": <код>, "amount": <число рублей или null>, "term_months": <число или null>}. '
    "Коды целей: " + "; ".join(f"{p.code} — {p.title} ({p.hint})" for p in PURPOSES.values()) + ". "
    "Правила: amount и term_months указывай, только если они прямо названы в тексте, иначе null — ничего не придумывай. "
    "Если цель непонятна, верни purpose null. "
    "Примеры: «надо обновить парк, взять два фургона» → "
    '{"purpose": "equipment", "amount": null, "term_months": null}; '
    "«клиенты платят через 60 дней, а поставщикам сейчас, тысяч 800» → "
    '{"purpose": "cash_gap", "amount": 800000, "term_months": null}; '
    "«хотим открыть вторую кофейню, полтора миллиона на ремонт» → "
    '{"purpose": "expansion", "amount": 1500000, "term_months": null}.'
)


def llm_available() -> bool:
    s = get_settings()
    if not s.llm_url:
        return False
    cached = _status_cache.get(s.llm_url)
    if cached and time.monotonic() - cached[0] < 30:
        return cached[1]
    ok = False
    try:
        r = httpx.get(s.llm_url.rstrip("/") + "/api/tags", timeout=1.0)
        ok = r.status_code == 200 and any(m.get("name", "").startswith(s.llm_model.split(":")[0])
                                          for m in r.json().get("models", []))
    except httpx.HTTPError:
        ok = False
    _status_cache[s.llm_url] = (time.monotonic(), ok)
    return ok


def _llm_extract(text: str) -> dict | None:
    s = get_settings()
    try:
        r = httpx.post(s.llm_url.rstrip("/") + "/api/chat", timeout=s.llm_timeout_sec, json={
            "model": s.llm_model, "stream": False, "format": "json", "options": {"temperature": 0},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text[:1000]}],
        })
        r.raise_for_status()
        data = json.loads(r.json()["message"]["content"])
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        log.warning("llm_failed err=%s", type(e).__name__)
        return None
    purpose = data.get("purpose")
    if purpose not in PURPOSES:
        return None
    amount = data.get("amount")
    term = data.get("term_months")
    return {"purpose": purpose,
            "amount": int(amount) if isinstance(amount, (int, float)) and 10_000 <= amount <= 1_000_000_000 else None,
            "term_months": int(term) if isinstance(term, (int, float)) and 1 <= term <= 120 else None}


def suggest(text: str | None, purpose: str | None, amount: int | None) -> dict:
    source = "form"
    term = None
    if text and not purpose:
        extracted = _llm_extract(text) if llm_available() else None
        rule_purpose, rule_amount, rule_term = purpose_from_text(text), amount_from_text(text), term_from_text(text)
        if extracted:
            source = "llm"
            purpose = extracted["purpose"]
            # Срок — тоже только если он назван; разбор по правилам точнее модели
            term = rule_term or (extracted["term_months"] if re.search(r"мес|год|лет", text.lower()) else None)
            # Модель не должна противоречить явным словам в тексте: если правила нашли признаки другой цели,
            # а для выбранной моделью — ни одного, верим тексту
            if rule_purpose and rule_purpose != purpose and purpose_scores(text).get(purpose, 0) == 0:
                log.info("llm_overridden purpose llm=%s rules=%s", purpose, rule_purpose)
                purpose, source = rule_purpose, "rules"
            # Сумма — только если она есть в тексте; точный разбор по правилам надёжнее ответа модели
            llm_amount = extracted["amount"] if mentions_amount(text) else None
            amount = amount or rule_amount or llm_amount
        else:
            source = "rules"
            purpose = rule_purpose
            amount = amount or rule_amount
            term = rule_term
    if not purpose:
        return {"source": source, "purpose": None, "amount": amount, "term_months": None, "recommendations": [],
                "message": "Не получилось понять цель. Выберите её из списка или опишите подробнее, на что нужны деньги."}
    recs = recommend(purpose, amount)
    return {
        "source": source, "purpose": purpose, "purpose_title": PURPOSES[purpose].title,
        "amount": amount, "term_months": term,
        "recommendations": [{"product_code": r.product_code, "name": PRODUCTS[r.product_code].name,
                             "fit": r.fit, "reason": r.reason} for r in recs],
        "message": None,
    }


def analyst_summary(app_scoring: dict | None, decision: dict | None) -> list[str]:
    """Короткая сводка для аналитика: что проверить в первую очередь. Детерминированная."""
    if not app_scoring:
        return ["Скоринг не выполнен: внешние данные не получены. Проверьте источники вручную."]
    out = []
    negatives = sorted((f for f in app_scoring.get("factors", []) if f["points"] < 0), key=lambda f: f["points"])
    for f in negatives[:3]:
        out.append(f"{f['title']}: {f['value']} ({f['points']} б.)")
    if decision and decision.get("recommended_outcome"):
        rec = decision["recommended_outcome"]
        offer = decision.get("offer")
        text = {"APPROVED": "одобрить", "COUNTER_OFFER": "встречное предложение", "REJECTED": "отказать"}.get(rec, rec)
        if offer:
            text += f" — {offer['amount']:,} ₽ на {offer['term_months']} мес. под {offer['rate']}%".replace(",", " ")
        out.append(f"Рекомендация системы: {text}")
    return out or ["Негативных факторов нет."]