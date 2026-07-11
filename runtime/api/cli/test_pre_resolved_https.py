"""Connection, proxy, TLS, and SNI tests for caller-owned HTTPS."""

from __future__ import annotations

import socket
import ssl
import urllib.request

import pytest

from yoke_cli.transport import pre_resolved_https
from yoke_cli.transport import pre_resolved_https_connection as connection_module


class _MutableClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.parametrize(
    "proxies,expected",
    (
        ({}, ("api.example", 443)),
        ({"https": "http://proxy.example:8080"}, ("proxy.example", 8080)),
        ({"https": "proxy.example:3128"}, ("proxy.example", 3128)),
    ),
)
def test_connection_target_selects_direct_or_http_proxy(
    monkeypatch,
    proxies,
    expected,
) -> None:
    monkeypatch.setattr(
        pre_resolved_https.urllib.request,
        "getproxies",
        lambda: proxies,
    )
    monkeypatch.setattr(
        pre_resolved_https.urllib.request,
        "proxy_bypass",
        lambda _host: False,
    )
    target = pre_resolved_https._connection_target(
        urllib.request.Request("https://api.example/operation")
    )

    assert (target.host, target.port) == expected


def test_proxy_bypass_keeps_direct_target(monkeypatch) -> None:
    monkeypatch.setattr(
        pre_resolved_https.urllib.request,
        "getproxies",
        lambda: {"https": "http://proxy.example:8080"},
    )
    monkeypatch.setattr(
        pre_resolved_https.urllib.request,
        "proxy_bypass",
        lambda _host: True,
    )

    target = pre_resolved_https._connection_target(
        urllib.request.Request("https://api.example/operation")
    )

    assert (target.host, target.port) == ("api.example", 443)


def test_https_proxy_transport_is_explicitly_refused(monkeypatch) -> None:
    monkeypatch.setattr(
        pre_resolved_https.urllib.request,
        "getproxies",
        lambda: {"https": "https://proxy.example:8443"},
    )
    monkeypatch.setattr(
        pre_resolved_https.urllib.request,
        "proxy_bypass",
        lambda _host: False,
    )

    with pytest.raises(pre_resolved_https.ResponseOpenError, match="HTTP proxy"):
        pre_resolved_https._connection_target(
            urllib.request.Request("https://api.example/operation")
        )


class _ConnectSocket:
    def __init__(self, clock: _MutableClock, *, advance: float = 0.0) -> None:
        self.clock = clock
        self.advance = advance
        self.connected_to = None
        self.closed = False
        self.timeouts: list[float] = []

    def settimeout(self, seconds: float) -> None:
        self.timeouts.append(seconds)

    def bind(self, _source) -> None:
        return None

    def connect(self, address) -> None:
        self.connected_to = address
        self.clock.advance(self.advance)

    def close(self) -> None:
        self.closed = True


def _connection(clock: _MutableClock):
    return connection_module._PreResolvedHTTPSConnection(
        "api.example",
        address_book={
            ("api.example", 443): [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.10", 443))
            ]
        },
        deadline=1.0,
        clock=clock,
        context=ssl.create_default_context(),
    )


def test_pre_resolved_connection_uses_resolved_ip_without_dns(monkeypatch) -> None:
    clock = _MutableClock()
    sock = _ConnectSocket(clock)
    monkeypatch.setattr(connection_module.socket, "socket", lambda *_args: sock)

    selected = _connection(clock)._create_pre_resolved_connection(("api.example", 443))

    assert selected is sock
    assert sock.connected_to == ("192.0.2.10", 443)
    assert sock.timeouts == pytest.approx([1.0])


def test_late_connect_is_closed_and_rejected(monkeypatch) -> None:
    clock = _MutableClock()
    sock = _ConnectSocket(clock, advance=1.1)
    monkeypatch.setattr(connection_module.socket, "socket", lambda *_args: sock)

    with pytest.raises(connection_module.ResponseOpenDeadlineError):
        _connection(clock)._create_pre_resolved_connection(("api.example", 443))

    assert sock.closed is True


class _RawSocket:
    def __init__(self) -> None:
        self.blocking = None
        self.closed = False

    def setblocking(self, enabled: bool) -> None:
        self.blocking = enabled

    def close(self) -> None:
        self.closed = True


class _WrappedSocket:
    def __init__(self, *, handshake_error: Exception | None = None) -> None:
        self.handshake_error = handshake_error
        self.timeouts: list[float] = []
        self.closed = False

    def do_handshake(self) -> None:
        if self.handshake_error is not None:
            raise self.handshake_error

    def settimeout(self, seconds: float) -> None:
        self.timeouts.append(seconds)

    def close(self) -> None:
        self.closed = True


class _TLSContext:
    def __init__(self, wrapped: _WrappedSocket) -> None:
        self.wrapped = wrapped
        self.calls = []

    def wrap_socket(self, raw, **kwargs):
        self.calls.append((raw, kwargs))
        return self.wrapped


@pytest.mark.parametrize(
    "tunnel_host,expected_sni",
    ((None, "api.example"), ("target.example", "target.example")),
)
def test_tls_uses_original_hostname_for_sni(
    monkeypatch,
    tunnel_host,
    expected_sni,
) -> None:
    clock = _MutableClock()
    raw = _RawSocket()
    wrapped = _WrappedSocket()
    context = _TLSContext(wrapped)
    selected = _connection(clock)
    selected._context = context
    selected._tunnel_host = tunnel_host
    monkeypatch.setattr(
        connection_module.http.client.HTTPConnection,
        "connect",
        lambda connection: setattr(connection, "sock", raw),
    )

    selected.connect()

    assert raw.blocking is False
    assert context.calls[0][1] == {
        "server_hostname": expected_sni,
        "do_handshake_on_connect": False,
    }
    assert wrapped.timeouts == pytest.approx([1.0])


def test_slow_tls_handshake_closes_socket(monkeypatch) -> None:
    clock = _MutableClock()
    raw = _RawSocket()
    wrapped = _WrappedSocket(handshake_error=ssl.SSLWantReadError())
    context = _TLSContext(wrapped)
    selected = _connection(clock)
    selected._context = context
    monkeypatch.setattr(
        connection_module.http.client.HTTPConnection,
        "connect",
        lambda connection: setattr(connection, "sock", raw),
    )
    monkeypatch.setattr(
        connection_module.select,
        "select",
        lambda *_args, **_kwargs: ([], [], []),
    )

    with pytest.raises(
        connection_module.ResponseOpenDeadlineError,
        match="TLS handshake",
    ):
        selected.connect()

    assert raw.closed is True
    assert wrapped.closed is True
