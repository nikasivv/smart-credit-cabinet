from app.integrations.resilience import CircuitBreaker, CircuitOpenError, retry


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _fail():
    raise ConnectionError("down")


def test_breaker_opens_after_threshold_and_recovers():
    clock = Clock()
    cb = CircuitBreaker("x", failure_threshold=2, reset_timeout_sec=10, clock=clock)
    for _ in range(2):
        try:
            cb.call(_fail)
        except ConnectionError:
            pass
    assert cb.state == "OPEN"
    try:
        cb.call(lambda: 1)
    except CircuitOpenError:
        pass
    else:
        raise AssertionError("разомкнутая цепь не должна пропускать вызовы")
    clock.t = 11
    assert cb.state == "HALF_OPEN"
    assert cb.call(lambda: 42) == 42 and cb.state == "CLOSED"


def test_half_open_failure_reopens():
    clock = Clock()
    cb = CircuitBreaker("x", failure_threshold=1, reset_timeout_sec=5, clock=clock)
    try:
        cb.call(_fail)
    except ConnectionError:
        pass
    clock.t = 6
    try:
        cb.call(_fail)
    except ConnectionError:
        pass
    assert cb.state == "OPEN"


def test_retry_counts_attempts():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError
        return "ok"

    assert retry(flaky, attempts=3, sleep=lambda _: None) == ("ok", 3)


def test_retry_gives_up():
    try:
        retry(_fail, attempts=2, sleep=lambda _: None)
    except ConnectionError:
        return
    raise AssertionError


def test_worker_heartbeat(tmp_path, monkeypatch):
    """Проверка здоровья воркера: свежий пульс — жив, старый или отсутствующий — нет."""
    import os
    import time

    from app import worker
    monkeypatch.setattr(worker, "HEARTBEAT_FILE", tmp_path / "hb")
    assert worker.is_alive() is False
    worker.heartbeat()
    assert worker.is_alive() is True
    old = time.time() - 600
    os.utime(worker.HEARTBEAT_FILE, (old, old))
    assert worker.is_alive() is False
