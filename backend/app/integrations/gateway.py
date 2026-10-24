"""Шлюз к внешним источникам данных.

В проверяемой версии все источники — локальный сервис-симулятор (mocks/),
контракты упрощены, но сохраняют смысл интеграций:
* ЕГРЮЛ/ЕГРИП — существование и статус бизнеса, дата регистрации, ОКВЭД, руководитель;
* ФНС «Прозрачный бизнес» — выручка, налоговая задолженность, массовый адрес;
* БКИ — действующие обязательства, платежи, просрочки, запросы.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from ..config import get_settings
from ..security import mask_inn
from .resilience import CircuitBreaker, CircuitOpenError, retry

log = logging.getLogger("scc.integrations")


class IntegrationUnavailable(Exception):
    def __init__(self, source: str, reason: str):
        self.source, self.reason = source, reason
        super().__init__(f"{source}: {reason}")


class NotFoundInSource(Exception):
    def __init__(self, source: str):
        self.source = source
        super().__init__(f"{source}: компания не найдена")


@dataclass
class CallInfo:
    source: str
    attempts: int
    latency_ms: int


class DataGateway(Protocol):
    def egrul(self, inn: str) -> tuple[dict, CallInfo]: ...
    def fns(self, inn: str) -> tuple[dict, CallInfo]: ...
    def bki(self, inn: str) -> tuple[dict, CallInfo]: ...


_breakers = {name: CircuitBreaker(name) for name in ("egrul", "fns", "bki")}


class HttpDataGateway:
    PATHS = {"egrul": "/egrul/{inn}", "fns": "/fns/transparent-business/{inn}", "bki": "/bki/{inn}/report"}

    def __init__(self, base_url: str | None = None):
        s = get_settings()
        self.base_url = (base_url or s.integrations_url).rstrip("/")
        self.timeout = s.integrations_timeout_sec
        self.attempts = s.integrations_retries + 1

    def _get(self, source: str, inn: str) -> tuple[dict, CallInfo]:
        url = self.base_url + self.PATHS[source].format(inn=inn)
        breaker = _breakers[source]

        def once() -> dict | None:
            r = httpx.get(url, timeout=self.timeout, headers={"X-Client": "scc-credit-pipeline"})
            if r.status_code == 404:
                return None  # «не найдено» — штатный ответ источника, не сбой
            r.raise_for_status()
            return r.json()

        started = time.perf_counter()
        try:
            data, attempts = retry(lambda: breaker.call(once), self.attempts,
                                   retry_on=(httpx.HTTPError,))
        except CircuitOpenError as e:
            raise IntegrationUnavailable(source, str(e)) from e
        except httpx.HTTPError as e:
            log.warning("integration_failed source=%s inn=%s err=%s", source, mask_inn(inn), type(e).__name__)
            raise IntegrationUnavailable(source, f"нет ответа после {self.attempts} попыток") from e
        if data is None:
            raise NotFoundInSource(source)
        latency = int((time.perf_counter() - started) * 1000)
        log.info("integration_ok source=%s inn=%s attempts=%s latency_ms=%s", source, mask_inn(inn), attempts, latency)
        return data, CallInfo(source, attempts, latency)

    def egrul(self, inn: str) -> tuple[dict, CallInfo]:
        return self._get("egrul", inn)

    def fns(self, inn: str) -> tuple[dict, CallInfo]:
        return self._get("fns", inn)

    def bki(self, inn: str) -> tuple[dict, CallInfo]:
        return self._get("bki", inn)


_gateway: DataGateway | None = None


def get_gateway() -> DataGateway:
    global _gateway
    if _gateway is None:
        _gateway = HttpDataGateway()
    return _gateway


def set_gateway(gw: DataGateway | None) -> None:
    """Подмена шлюза в тестах."""
    global _gateway
    _gateway = gw
