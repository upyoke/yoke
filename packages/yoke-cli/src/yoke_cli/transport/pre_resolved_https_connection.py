"""Pre-resolved HTTPS connections with deadline-aware TLS and headers."""

from __future__ import annotations

import functools
import http.client
import select
import socket
import ssl
import urllib.request
from collections.abc import Callable
from typing import Any

from yoke_cli.transport.response_deadline_errors import (
    ResponseOpenDeadlineError,
    ResponseOpenError,
)


class PreResolvedHTTPSHandler(urllib.request.HTTPSHandler):
    """HTTPS handler whose connections cannot perform ambient DNS."""

    def __init__(
        self,
        *,
        address_book: dict[tuple[str, int], list[tuple[Any, ...]]],
        deadline: float,
        clock: Callable[[], float],
    ) -> None:
        super().__init__()
        self._address_book = address_book
        self._deadline = deadline
        self._clock = clock

    def https_open(self, request):
        connection = functools.partial(
            _PreResolvedHTTPSConnection,
            address_book=self._address_book,
            deadline=self._deadline,
            clock=self._clock,
        )
        return self.do_open(
            connection,
            request,
            context=self._context,
            check_hostname=self._check_hostname,
        )


class _PreResolvedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        *,
        address_book: dict[tuple[str, int], list[tuple[Any, ...]]],
        deadline: float,
        clock: Callable[[], float],
        **kwargs: Any,
    ) -> None:
        super().__init__(host, **kwargs)
        self._address_book = address_book
        self._deadline = deadline
        self._deadline_clock = clock
        self._create_connection = self._create_pre_resolved_connection
        self.response_class = functools.partial(
            _DeadlineHTTPResponse,
            deadline=deadline,
            clock=clock,
        )

    def connect(self) -> None:
        """Connect and complete TLS with the same absolute deadline."""
        http.client.HTTPConnection.connect(self)
        if self.sock is None:
            raise ResponseOpenError("HTTPS connection did not create a socket")
        server_hostname = self._tunnel_host or self.host
        raw_socket = self.sock
        raw_socket.setblocking(False)
        try:
            wrapped = self._context.wrap_socket(
                raw_socket,
                server_hostname=server_hostname,
                do_handshake_on_connect=False,
            )
            self.sock = wrapped
            while True:
                try:
                    wrapped.do_handshake()
                    break
                except ssl.SSLWantReadError:
                    _wait_for_socket(
                        wrapped,
                        readable=True,
                        deadline=self._deadline,
                        clock=self._deadline_clock,
                    )
                except ssl.SSLWantWriteError:
                    _wait_for_socket(
                        wrapped,
                        readable=False,
                        deadline=self._deadline,
                        clock=self._deadline_clock,
                    )
            wrapped.settimeout(_remaining(self._deadline, self._deadline_clock))
        except Exception:
            active_socket = self.sock
            if active_socket is not None:
                active_socket.close()
            if active_socket is not raw_socket:
                raw_socket.close()
            raise

    def _create_pre_resolved_connection(
        self,
        address: tuple[str, int],
        _timeout: Any = socket._GLOBAL_DEFAULT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        key = (_host_key(address[0]), int(address[1]))
        addresses = self._address_book.get(key)
        if not addresses:
            raise ResponseOpenError(
                "HTTPS connection target was not resolved by the deadline preflight"
            )
        last_error: OSError | None = None
        for family, socktype, proto, _canonname, sockaddr in addresses:
            sock: socket.socket | None = None
            try:
                sock = socket.socket(family, socktype, proto)
                sock.settimeout(_remaining(self._deadline, self._deadline_clock))
                if source_address:
                    sock.bind(source_address)
                sock.connect(sockaddr)
                _remaining(self._deadline, self._deadline_clock)
                return sock
            except OSError as exc:
                last_error = exc
                if sock is not None:
                    sock.close()
        if last_error is not None:
            raise last_error
        raise ResponseOpenError("HTTPS resolver returned no usable addresses")


class _DeadlineHTTPResponse(http.client.HTTPResponse):
    def __init__(
        self,
        sock: socket.socket,
        *args: Any,
        deadline: float,
        clock: Callable[[], float],
        **kwargs: Any,
    ) -> None:
        super().__init__(sock, *args, **kwargs)
        if self.fp is not None:
            self.fp = _DeadlineBufferedReader(
                self.fp,
                sock=sock,
                deadline=deadline,
                clock=clock,
            )


class _DeadlineBufferedReader:
    def __init__(
        self,
        wrapped: Any,
        *,
        sock: socket.socket,
        deadline: float,
        clock: Callable[[], float],
    ) -> None:
        self._wrapped = wrapped
        self._sock = sock
        self._deadline = deadline
        self._clock = clock

    def read1(self, size: int = -1) -> bytes:
        self._set_timeout()
        try:
            raw = self._wrapped.read1(size)
        except TimeoutError:
            raise ResponseOpenDeadlineError(
                "HTTPS response headers exceeded the time limit"
            ) from None
        self._check()
        return raw

    def read(self, size: int = -1) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining != 0:
            amount = 64 * 1024 if remaining < 0 else min(64 * 1024, remaining)
            chunk = self.read1(amount)
            if not chunk:
                break
            chunks.append(chunk)
            if remaining > 0:
                remaining -= len(chunk)
        return b"".join(chunks)

    def readline(self, limit: int = -1) -> bytes:
        line = bytearray()
        while limit < 0 or len(line) < limit:
            chunk = self.read1(1)
            if not chunk:
                break
            line.extend(chunk)
            if chunk == b"\n":
                break
        return bytes(line)

    def close(self) -> None:
        self._wrapped.close()

    @property
    def closed(self) -> bool:
        return bool(self._wrapped.closed)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)

    def _set_timeout(self) -> None:
        self._sock.settimeout(_remaining(self._deadline, self._clock))

    def _check(self) -> None:
        if self._clock() >= self._deadline:
            raise ResponseOpenDeadlineError(
                "HTTPS response headers exceeded the time limit"
            )


def _wait_for_socket(
    sock: socket.socket,
    *,
    readable: bool,
    deadline: float,
    clock: Callable[[], float],
) -> None:
    timeout = _remaining(deadline, clock)
    reads = [sock] if readable else []
    writes = [] if readable else [sock]
    ready_reads, ready_writes, _errors = select.select(reads, writes, [], timeout)
    if not ready_reads and not ready_writes:
        raise ResponseOpenDeadlineError("HTTPS TLS handshake exceeded its time limit")


def _host_key(value: str) -> str:
    return str(value or "").strip("[]").casefold()


def _remaining(deadline: float, clock: Callable[[], float]) -> float:
    remaining = deadline - clock()
    if remaining <= 0:
        raise ResponseOpenDeadlineError("HTTPS open exceeded its time limit")
    return remaining


__all__ = ["PreResolvedHTTPSHandler"]
