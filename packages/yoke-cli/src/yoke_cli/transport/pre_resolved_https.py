"""Caller-owned HTTPS opening over deadline-bounded DNS results."""

from __future__ import annotations

import queue
import socket
import threading
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from yoke_cli.transport.pre_resolved_https_connection import (
    PreResolvedHTTPSHandler,
)
from yoke_cli.transport.response_deadline_errors import (
    ResponseOpenDeadlineError,
    ResponseOpenError,
)


@dataclass(frozen=True)
class _ConnectionTarget:
    host: str
    port: int


def open_https_caller_owned(
    request: urllib.request.Request,
    *,
    deadline: float,
    handlers: Iterable[Any],
    clock: Callable[[], float],
) -> Any:
    """Open HTTPS synchronously after a bounded, DNS-only preflight."""
    target = _connection_target(request)
    addresses = _resolve_target(target, deadline=deadline, clock=clock)
    address_book = {(_host_key(target.host), target.port): addresses}
    https_handler = PreResolvedHTTPSHandler(
        address_book=address_book,
        deadline=deadline,
        clock=clock,
    )
    opener = urllib.request.build_opener(*tuple(handlers), https_handler)
    response = opener.open(request, timeout=_remaining(deadline, clock))
    if clock() >= deadline:
        _close(response)
        raise ResponseOpenDeadlineError("HTTPS open exceeded its time limit")
    return response


def _resolve_target(
    target: _ConnectionTarget,
    *,
    deadline: float,
    clock: Callable[[], float],
) -> list[tuple[Any, ...]]:
    def resolve() -> list[tuple[Any, ...]]:
        return socket.getaddrinfo(
            target.host,
            target.port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )

    result = _run_dns_only(resolve, deadline=deadline, clock=clock)
    if not result:
        raise ResponseOpenError("HTTPS resolver returned no addresses")
    return result


def _run_dns_only(
    resolve: Callable[[], list[tuple[Any, ...]]],
    *,
    deadline: float,
    clock: Callable[[], float],
) -> list[tuple[Any, ...]]:
    outcome: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
    cancelled = threading.Event()

    def run() -> None:
        try:
            selected = ("value", resolve())
        except Exception as exc:
            selected = ("error", exc)
        if not cancelled.is_set():
            outcome.put(selected)

    timeout = _remaining(deadline, clock)
    worker = threading.Thread(target=run, name="yoke-dns-deadline", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        cancelled.set()
        raise ResponseOpenDeadlineError("HTTPS DNS lookup exceeded its time limit")
    kind, selected = outcome.get_nowait()
    if clock() >= deadline:
        raise ResponseOpenDeadlineError("HTTPS DNS lookup exceeded its time limit")
    if kind == "error":
        raise selected
    return selected


def _connection_target(request: urllib.request.Request) -> _ConnectionTarget:
    parsed = urllib.parse.urlsplit(request.full_url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ResponseOpenError("deadline-owned requests require an HTTPS URL")
    direct = _ConnectionTarget(parsed.hostname, parsed.port or 443)
    proxy_url = urllib.request.getproxies().get("https")
    if not proxy_url or urllib.request.proxy_bypass(parsed.hostname):
        return direct
    selected_proxy = proxy_url if "://" in proxy_url else f"//{proxy_url}"
    proxy = urllib.parse.urlsplit(selected_proxy)
    if not proxy.hostname:
        raise ResponseOpenError("configured HTTPS proxy has no hostname")
    proxy_scheme = proxy.scheme.lower()
    if proxy_scheme not in {"", "http"}:
        raise ResponseOpenError(
            "deadline-owned HTTPS requests require a direct connection or HTTP proxy"
        )
    return _ConnectionTarget(proxy.hostname, proxy.port or 80)


def _host_key(value: str) -> str:
    return str(value or "").strip("[]").casefold()


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


__all__ = [
    "ResponseOpenDeadlineError",
    "ResponseOpenError",
    "open_https_caller_owned",
]
