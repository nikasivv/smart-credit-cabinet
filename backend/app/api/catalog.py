from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..domain.policy import make_offer
from ..domain.products import DOCUMENTS, PRODUCT_CATALOG_VERSION, PRODUCTS, PURPOSES
from ..errors import Conflict, ServiceUnavailable, ValidationFailed
from ..integrations.gateway import IntegrationUnavailable, NotFoundInSource, get_gateway
from ..models import Company, User
from ..schemas import (CalcIn, CalcOut, CatalogOut, LoginIn, ProductOut, PurposeOut, RegisterIn, SuggestIn, TokenOut,
                       UserOut)
from ..security import create_token, current_user, hash_password, mask_inn, verify_password
from ..services import assistant

log = logging.getLogger("scc.auth")

auth = APIRouter(prefix="/api/auth", tags=["auth"])
catalog = APIRouter(prefix="/api", tags=["catalog"])


@auth.post("/login", response_model=TokenOut, summary="Вход по email и паролю")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, detail="Неверный email или пароль")
    return TokenOut(access_token=create_token(user), user=UserOut.model_validate(user))


@auth.post("/register", response_model=TokenOut, status_code=201, summary="Регистрация клиента по ИНН")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """Название, форму бизнеса, ОКВЭД и регион банк берёт из ЕГРЮЛ/ЕГРИП — клиент вводит только ИНН и контакты.
    После регистрации пользователь сразу входит в кабинет."""
    if db.scalar(select(User).where(User.email == body.email)):
        raise Conflict("Пользователь с таким email уже есть — войдите", code="email_taken",
                       details=[{"field": "email", "message": "Этот email уже зарегистрирован"}])
    company = db.scalar(select(Company).where(Company.inn == body.inn))
    if company and db.scalar(select(User).where(User.company_id == company.id)):
        raise Conflict("Компания уже подключена к кабинету — войдите под её аккаунтом", code="company_taken",
                       details=[{"field": "inn", "message": "Компания с этим ИНН уже зарегистрирована"}])
    if company is None:
        try:
            e, _ = get_gateway().egrul(body.inn)
        except NotFoundInSource:
            raise ValidationFailed("Компания не найдена", details=[
                {"field": "inn", "message": "Компании с таким ИНН нет в ЕГРЮЛ/ЕГРИП"}])
        except IntegrationUnavailable:
            raise ServiceUnavailable("Реестр ЕГРЮЛ/ЕГРИП сейчас не отвечает — попробуйте через минуту")
        ip = len(body.inn) == 12
        company = Company(inn=body.inn, legal_form=e.get("legal_form") or ("IP" if ip else "OOO"),
                          name=e.get("name") or f"{'ИП' if ip else 'ООО'} с ИНН {body.inn}",
                          okved=e.get("okved"), okved_name=e.get("okved_name"), region=e.get("region"))
        db.add(company)
        db.flush()
    user = User(email=body.email, password_hash=hash_password(body.password), full_name=body.full_name,
                position=body.position or None, role="CLIENT", company_id=company.id)
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("client_registered inn=%s user_id=%s", mask_inn(body.inn), user.id)
    return TokenOut(access_token=create_token(user), user=UserOut.model_validate(user))


@auth.get("/me", response_model=UserOut, summary="Текущий пользователь")
def me(user: User = Depends(current_user)):
    return user


@catalog.get("/catalog", response_model=CatalogOut, summary="Продукты, цели финансирования, типы документов")
def get_catalog():
    return CatalogOut(
        version=PRODUCT_CATALOG_VERSION,
        products=[ProductOut(code=p.code, name=p.name, tagline=p.tagline, description=p.description,
                             min_amount=p.min_amount, max_amount=p.max_amount, min_term=p.min_term,
                             max_term=p.max_term, base_rate=p.base_rate, requires_collateral=p.requires_collateral,
                             purposes=list(p.purposes), features=list(p.features)) for p in PRODUCTS.values()],
        purposes=[PurposeOut(code=p.code, title=p.title, hint=p.hint) for p in PURPOSES.values()],
        documents=DOCUMENTS,
    )


@catalog.post("/calculator", response_model=CalcOut, summary="Предварительный расчёт платежа")
def calculate(body: CalcIn):
    p = PRODUCTS.get(body.product_code)
    if p is None:
        raise ValidationFailed("Неизвестный продукт", [{"field": "product_code", "message": "Выберите продукт"}])
    o = make_offer(body.amount, body.term_months, p.base_rate)
    return CalcOut(rate_from=p.base_rate, monthly_payment_from=o.monthly_payment, overpayment_from=o.overpayment,
                   note="Расчёт по минимальной ставке. Итоговая ставка зависит от оценки заявки.")


@catalog.post("/assistant/suggest", summary="Подбор продукта по описанию потребности")
def suggest(body: SuggestIn, _: User = Depends(current_user)):
    return assistant.suggest(body.text, body.purpose, body.amount)


@catalog.get("/assistant/status", summary="Доступна ли языковая модель")
def assistant_status(_: User = Depends(current_user)):
    return {"llm_available": assistant.llm_available()}