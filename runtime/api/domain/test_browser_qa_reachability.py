"""Browser QA reachability: cookie-preserving GET, not HEAD or cookie-less curl."""

from __future__ import annotations

import ssl
import threading
import urllib.parse
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

from yoke_core.domain import browser_qa_freshness as freshness

SECRET_TOKEN = "super-secret-login-token"
SESSION_COOKIE = "review_session=ok"


@contextmanager
def _serve(handler_cls: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


def _login_handler(methods: list[str]) -> type[BaseHTTPRequestHandler]:
    class Handler(_QuietHandler):
        def do_HEAD(self) -> None:  # noqa: N802 - http.server API
            methods.append("HEAD")
            self.send_error(401)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            methods.append("GET")
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/login":
                self.send_response(302)
                self.send_header("Set-Cookie", f"{SESSION_COOKIE}; HttpOnly; Path=/")
                self.send_header("Location", "/app")
                self.end_headers()
                return
            if parsed.path == "/app":
                if SESSION_COOKIE in (self.headers.get("Cookie") or ""):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok")
                    return
                self.send_error(401)
                return
            self.send_error(404)

    return Handler


class _OffOriginHandler(_QuietHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self.send_response(302)
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}; HttpOnly; Path=/")
        self.send_header("Location", "http://evil.example.test/steal")
        self.end_headers()


def test_login_token_redirect_with_httponly_cookie_is_reachable() -> None:
    """HEAD and cookie-less curl 401 here; GET plus a jar follows like a browser."""
    methods: list[str] = []
    with _serve(_login_handler(methods)) as origin:
        url = f"{origin}/login?token={SECRET_TOKEN}"
        assert freshness._validate_reachability(url) is None
    assert "HEAD" not in methods
    assert methods[0] == "GET"


def test_login_token_is_not_echoed_in_any_probe_error() -> None:
    with _serve(_login_handler([])) as origin:
        err = freshness._validate_reachability(f"{origin}/app?token={SECRET_TOKEN}")
    assert err is not None
    assert "401" in err
    assert SECRET_TOKEN not in err
    assert SESSION_COOKIE not in err
    assert "token=" not in err


def test_genuine_401_without_a_cookie_exchange_still_refuses() -> None:
    with _serve(_login_handler([])) as origin:
        err = freshness._validate_reachability(f"{origin}/app")
    assert err is not None
    assert "401" in err
    assert SESSION_COOKIE not in err


def test_off_origin_redirect_is_refused_and_does_not_leak_cookies() -> None:
    with _serve(_OffOriginHandler) as origin:
        err = freshness._validate_reachability(f"{origin}/login?token={SECRET_TOKEN}")
    assert err is not None
    assert "off-origin" in err
    assert SECRET_TOKEN not in err
    assert SESSION_COOKIE not in err
    assert "evil.example.test" not in err


def test_timeout_is_named_without_raising(monkeypatch) -> None:
    class _Timeout:
        def open(self, *_args, **_kwargs):
            raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: _Timeout())
    monkeypatch.setattr(freshness.socket, "getaddrinfo", lambda *_: [("AF",)])
    err = freshness._validate_reachability("http://preview.example.test/app")
    assert err is not None
    assert "timed out" in err
    assert "preview.example.test" in err


def test_tls_failure_is_named_without_raising(monkeypatch) -> None:
    class _Tls:
        def open(self, *_args, **_kwargs):
            raise ssl.SSLError("certificate verify failed")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: _Tls())
    monkeypatch.setattr(freshness.socket, "getaddrinfo", lambda *_: [("AF",)])
    err = freshness._validate_reachability("https://preview.example.test/app")
    assert err is not None
    assert "TLS verification failed" in err


def test_dns_failure_names_the_host() -> None:
    err = freshness._validate_reachability("http://no-such-host.invalid/app")
    assert err is not None
    assert "DNS resolution failed" in err
    assert "no-such-host.invalid" in err
