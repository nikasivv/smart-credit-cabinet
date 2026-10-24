"""Retry с экспоненциальной задержкой и circuit breaker.

Без внешних зависимостей, чтобы поведение было прозрачным и тестируемым.
"""
from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    """CLOSED → (N ошибок подряд) → OPEN → (пауза) → HALF_OPEN → (успех) → CLOSED."""

    def __init__(self, name: str, failure_threshold: int = 3, reset_timeout_sec: float = 15.0,
                 clock: Callable[[], float] = time.monotonic):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout_sec = reset_timeout_sec
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "CLOSED"
            if self._clock() - self._opened_at >= self.reset_timeout_sec:
                return "HALF_OPEN"
            return "OPEN"

    def call(self, fn: Callable[[], T]) -> T:
        if self.state == "OPEN":
            raise CircuitOpenError(f"{self.name}: цепь разомкнута, источник временно не опрашивается")
        try:
            result = fn()
        except Exception:
            with self._lock:
                self._failures += 1
                if self._failures >= self.failure_threshold or self._opened_at is not None:
                    self._opened_at = self._clock()
            raise
        with self._lock:
            self._failures = 0
            self._opened_at = None
        return result


def retry(fn: Callable[[], T], attempts: int, base_delay: float = 0.2,
          retry_on: tuple[type[BaseException], ...] = (Exception,),
          sleep: Callable[[float], None] = time.sleep) -> tuple[T, int]:
    """Возвращает (результат, число попыток)."""
    last: BaseException | None = None
    for i in range(1, attempts + 1):
        try:
            return fn(), i
        except CircuitOpenError:
            raise
        except retry_on as e:  # noqa: PERF203
            last = e
            if i < attempts:
                sleep(base_delay * 2 ** (i - 1) + random.uniform(0, base_delay / 2))
    assert last is not None
    raise last
