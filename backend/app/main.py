"""Умный кредитный кабинет предпринимателя — API."""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .api.bank import admin, analyst, health
from .api.catalog import auth, catalog
from .api.client import router as client
from .config import get_settings
from .errors import AppError
from .logging_setup import request_id_var, setup_logging

setup_logging()
log = logging.getLogger("scc.api")
settings = get_settings()

app = FastAPI(
    title="Умный кредитный кабинет предпринимателя",
    version="1.0.0",
    description=(
        "Цифровой кредитный конвейер для малого и микробизнеса: клиентский кабинет, "
        "автоматическая обработка заявки (валидация → обогащение → скоринг → решение), "
        "рабочее место кредитного аналитика. Внешние источники (ЕГРЮЛ, ФНС, БКИ) смоделированы."
    ),
    openapi_tags=[
        {"name": "auth", "description": "Вход и профиль"},
        {"name": "catalog", "description": "Продукты, калькулятор, подбор продукта"},
        {"name": "client", "description": "Кабинет клиента: заявки, документы, блок «Ваши заявки и предложения»"},
        {"name": "analyst", "description": "Рабочее место кредитного аналитика"},
        {"name": "admin", "description": "Аудит, очередь задач, кредитная политика"},
        {"name": "health", "description": "Проверки живости и готовности"},
    ],
)

app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
                   allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type",
                                                                          "Idempotency-Key", "X-Request-ID"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    token = request_id_var.set(rid)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        ms = int((time.perf_counter() - started) * 1000)
        if not request.url.path.startswith("/health"):
            log.info("http %s %s %s %sms", request.method, request.url.path, response.status_code, ms)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


def _problem(status: int, code: str, message: str, details: list | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, media_type="application/problem+json",
                        content={"code": code, "message": message, "details": details or [],
                                 "request_id": request_id_var.get()})


@app.exception_handler(AppError)
async def app_error(_: Request, e: AppError):
    return _problem(e.status_code, e.code, e.message, e.details)


@app.exception_handler(HTTPException)
async def http_error(_: Request, e: HTTPException):
    code = {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(e.status_code, "http_error")
    resp = _problem(e.status_code, code, str(e.detail))
    if e.headers:
        resp.headers.update(e.headers)
    return resp


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, e: RequestValidationError):
    details = [{"field": ".".join(str(x) for x in err["loc"][1:]), "message": err["msg"]} for err in e.errors()]
    return _problem(422, "validation_failed", "Проверьте введённые данные", details)


@app.exception_handler(Exception)
async def unhandled(_: Request, e: Exception):
    log.exception("unhandled_error")
    return _problem(500, "internal_error", "Внутренняя ошибка. Сообщите в поддержку номер запроса")


for r in (health, auth, catalog, client, analyst, admin):
    app.include_router(r)
