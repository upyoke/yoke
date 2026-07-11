"""Whole-open deadlines for replay-safe and caller-owned HTTPS requests."""

from __future__ import annotations

import queue
import threading
import urllib.request
from collections.abc import Callable, Iterable
from typing import Any

from yoke_cli.transport import response_deadline_read
from yoke_cli.transport.pre_resolved_https import (
    ResponseOpenDeadlineError,
    ResponseOpenError,
    open_https_caller_owned as _open_https_caller_owned,
)


def open_replay_safe(
    request: urllib.request.Request,
    *,
    opener: Callable[..., Any],
    deadline: float,
    clock: Callable[[], float] | None = None,
) -> Any:
    """Open a replay-safe request in a fenced daemon worker."""
    selected_clock = clock or response_deadline_read.monotonic
    timeout = _remaining(deadline, selected_clock)
    outcome: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
    state_lock = threading.Lock()
    cancelled = False

    def run() -> None:
        nonlocal cancelled
        try:
            value = opener(request, timeout=timeout)
        except Exception as exc:
            selected = ("error", exc)
        else:
            selected = ("value", value)
        with state_lock:
            if cancelled:
                _close(selected[1])
                return
            outcome.put(selected)

    worker = threading.Thread(
        target=run,
        name="yoke-https-open-deadline",
        daemon=True,
    )
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        with state_lock:
            cancelled = True
            _drain_and_close(outcome)
        raise ResponseOpenDeadlineError("HTTPS open exceeded its time limit")
    try:
        kind, selected = outcome.get_nowait()
    except queue.Empty:
        raise ResponseOpenError("HTTPS open ended without a response") from None
    if selected_clock() >= deadline:
        with state_lock:
            cancelled = True
        _close(selected)
        raise ResponseOpenDeadlineError("HTTPS open exceeded its time limit")
    if kind == "error":
        raise selected
    return selected


def open_https_caller_owned(
    request: urllib.request.Request,
    *,
    deadline: float,
    handlers: Iterable[Any] = (),
    clock: Callable[[], float] | None = None,
) -> Any:
    """Open HTTPS synchronously after a bounded, DNS-only preflight."""
    return _open_https_caller_owned(
        request,
        deadline=deadline,
        handlers=handlers,
        clock=clock or response_deadline_read.monotonic,
    )


def open_caller_owned(
    request: urllib.request.Request,
    *,
    opener: Callable[..., Any],
    deadline: float,
    clock: Callable[[], float] | None = None,
) -> Any:
    """Call an injected opener synchronously and fence a late result."""
    selected_clock = clock or response_deadline_read.monotonic
    response = opener(request, timeout=_remaining(deadline, selected_clock))
    if selected_clock() >= deadline:
        _close(response)
        raise ResponseOpenDeadlineError("HTTPS open exceeded its time limit")
    return response


def _remaining(deadline: float, clock: Callable[[], float]) -> float:
    remaining = deadline - clock()
    if remaining <= 0:
        raise ResponseOpenDeadlineError("HTTPS open exceeded its time limit")
    return remaining


def _close(value: Any) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _drain_and_close(outcome: queue.Queue[tuple[str, Any]]) -> None:
    try:
        _kind, selected = outcome.get_nowait()
    except queue.Empty:
        return
    _close(selected)


__all__ = [
    "ResponseOpenDeadlineError",
    "ResponseOpenError",
    "open_caller_owned",
    "open_https_caller_owned",
    "open_replay_safe",
]
