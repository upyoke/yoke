"""Whole-open hard-wall and late-publication tests."""

from __future__ import annotations

import queue
import threading

import pytest

from yoke_cli.transport import pre_resolved_https
from yoke_cli.transport import pre_resolved_https_connection
from yoke_cli.transport import response_deadline_open


class _Response:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _MutableClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_cancel_publish_interleaving_closes_already_published_response(
    monkeypatch,
) -> None:
    """Cancellation and publication share one lock."""
    release_opener = threading.Event()
    published = threading.Event()
    response = _Response()
    real_thread = threading.Thread
    real_queue = queue.Queue

    class _ObservedQueue(real_queue):
        def put(self, item, *args, **kwargs):
            super().put(item, *args, **kwargs)
            published.set()

    class _ControlledThread:
        def __init__(self, *, target, name, daemon) -> None:
            self.inner = real_thread(target=target, name=name, daemon=daemon)

        def start(self) -> None:
            self.inner.start()

        def join(self, _timeout=None) -> None:
            return None

        def is_alive(self) -> bool:
            release_opener.set()
            assert published.wait(1.0)
            return True

    def opener(_request, timeout):
        del timeout
        assert release_opener.wait(1.0)
        return response

    monkeypatch.setattr(response_deadline_open.queue, "Queue", _ObservedQueue)
    monkeypatch.setattr(
        response_deadline_open.threading,
        "Thread",
        _ControlledThread,
    )

    with pytest.raises(response_deadline_open.ResponseOpenDeadlineError):
        response_deadline_open.open_replay_safe(
            object(),
            opener=opener,
            deadline=1.0,
            clock=lambda: 0.0,
        )

    assert response.closed is True


def test_caller_owned_open_closes_late_response(monkeypatch) -> None:
    clock = _MutableClock()
    response = _Response()

    class _FakeOpener:
        def open(self, _request, timeout):
            assert timeout == pytest.approx(1.0)
            clock.advance(1.1)
            return response

    monkeypatch.setattr(pre_resolved_https.urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr(
        pre_resolved_https.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    monkeypatch.setattr(
        pre_resolved_https.urllib.request,
        "build_opener",
        lambda *_handlers: _FakeOpener(),
    )

    request = pre_resolved_https.urllib.request.Request(
        "https://api.example/operation",
        method="POST",
        data=b"{}",
    )
    with pytest.raises(pre_resolved_https.ResponseOpenDeadlineError):
        pre_resolved_https.open_https_caller_owned(
            request,
            deadline=1.0,
            handlers=(),
            clock=clock,
        )

    assert response.closed is True


def test_status_header_reader_rejects_slow_trickle() -> None:
    clock = _MutableClock()

    class _Socket:
        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def settimeout(self, seconds: float) -> None:
            self.timeouts.append(seconds)

    class _Reader:
        closed = False

        def read1(self, _size: int = -1) -> bytes:
            clock.advance(0.6)
            return b"x"

        def close(self) -> None:
            return None

    sock = _Socket()
    reader = pre_resolved_https_connection._DeadlineBufferedReader(
        _Reader(),
        sock=sock,
        deadline=1.0,
        clock=clock,
    )

    with pytest.raises(pre_resolved_https.ResponseOpenDeadlineError):
        reader.readline()

    assert sock.timeouts == pytest.approx([1.0, 0.4])


def test_dns_timeout_detaches_only_resolver_work() -> None:
    release = threading.Event()

    def stalled_resolver():
        release.wait(1.0)
        return []

    import time

    try:
        with pytest.raises(pre_resolved_https.ResponseOpenDeadlineError):
            pre_resolved_https._run_dns_only(
                stalled_resolver,
                deadline=time.monotonic() + 0.02,
                clock=time.monotonic,
            )
    finally:
        release.set()
