"""Блок «Ваши заявки и предложения» в кабинете клиента.

Собирается из четырёх слоёв, по убыванию важности:
1. действия — что клиенту нужно сделать по заявкам прямо сейчас;
2. персональное предложение — например, овердрафт после выданного кредита;
3. события — последние изменения статусов заявок;
4. советы по заявке — короткие практичные подсказки, которые сокращают дозапросы и помогают
   выбрать продукт. Отбираются по форме бизнеса (ООО или ИП) и продуктам из заявок клиента.

Общих новостей и отраслевых материалов здесь нет намеренно: блок работает на кредитный путь.
У каждой карточки есть пояснение «почему вы это видите».
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Profile:
    legal_form: str            # IP | OOO
    products: set[str]         # продукты из заявок клиента


def rank_tips(tips: list[dict], p: Profile, limit: int = 3) -> list[dict]:
    ranked = []
    for t in tips:
        forms, products = set(t["legal_forms"]), set(t["products"])
        if "*" not in forms and p.legal_form not in forms:
            continue
        product_hit = bool(products & p.products)
        form_hit = p.legal_form in forms
        weight = (2 if product_hit else 0) + (1 if form_hit else 0)
        if product_hit:
            reason = "Связано с вашей заявкой или предложением банка"
        elif form_hit:
            reason = "Для " + ("индивидуальных предпринимателей" if p.legal_form == "IP" else "компаний")
        else:
            reason = "Полезно перед подачей заявки"
        ranked.append((weight, t["published_at"], {**t, "reason": reason, "relevance": weight}))
    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [r[2] for r in ranked[:limit]]
