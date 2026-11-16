"""Client connections on Windows: company CA, system proxy and error texts.

Yoke builds no TLS context or proxy table of its own. Python's default HTTPS
context reads the Windows certificate store, and ``urllib.request.getproxies``
falls back to the Internet Settings registry when no proxy variable is set.
These tests pin both facts, and map Windows Sockets codes (whose text is
localized) onto the existing named connection errors.
"""

from __future__ import annotations

import os
import ssl
import sys
import time
import urllib.error
import urllib.request

import pytest

from yoke_cli.transport import server_reach_failure as reach
from yoke_contracts import network_failure_reason, pre_resolved_https
from yoke_contracts.bounded_json_http import BoundedJsonHttpError, request_json
from yoke_contracts.pre_resolved_https_connection import (
    PreResolvedHTTPSHandler,
    _PreResolvedHTTPSConnection,
)

pytestmark = pytest.mark.windows

URL = "https://yoke.corp.example:8688"
COMPANY_ROOT = b"0\x82company-root-der"


def test_https_trusts_the_windows_certificate_store(monkeypatch) -> None:
    loaded: list[bytes] = []
    stores: list[str] = []

    def enum_certificates(store: str):
        stores.append(store)
        return [(COMPANY_ROOT, "x509_asn", True)] if store == "ROOT" else []

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ssl, "enum_certificates", enum_certificates, raising=False)
    monkeypatch.setattr(
        ssl.SSLContext,
        "load_verify_locations",
        lambda self, cafile=None, capath=None, cadata=None: loaded.append(cadata),
    )
    monkeypatch.setattr(ssl.SSLContext, "set_default_verify_paths", lambda self: None)

    # Yoke passes no context of its own: Python 3.13+ builds the default one
    # in the handler, 3.12 in the connection. Either way it is the default.
    handler = PreResolvedHTTPSHandler(address_book={}, deadline=0, clock=time.monotonic)
    context = handler._context or _PreResolvedHTTPSConnection(
        "yoke.corp.example", address_book={}, deadline=0, clock=time.monotonic
    )._context

    assert {"ROOT", "CA"} <= set(stores)
    assert COMPANY_ROOT in loaded
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_https_connects_through_the_proxy_python_reports(monkeypatch) -> None:
    monkeypatch.setattr(
        urllib.request, "getproxies", lambda: {"https": "proxy.corp.example:8080"}
    )
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda _host: False)

    target = pre_resolved_https._connection_target(urllib.request.Request(URL))

    assert (target.host, target.port) == ("proxy.corp.example", 8080)


@pytest.mark.skipif(os.name != "nt", reason="the registry fallback exists only on Windows")
def test_windows_system_proxy_setting_reaches_yoke(monkeypatch) -> None:
    monkeypatch.setattr(urllib.request, "getproxies_environment", lambda: {})
    monkeypatch.setattr(
        urllib.request,
        "getproxies_registry",
        lambda: {"https": "http://proxy.corp.example:3128"},
    )
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda _host: False)

    target = pre_resolved_https._connection_target(urllib.request.Request(URL))

    assert (target.host, target.port) == ("proxy.corp.example", 3128)


def _winsock_error(code: int, text: str) -> OSError:
    error = OSError(text)
    error.winerror = code
    return error


def _described(cause: BaseException) -> str:
    def opener(*_args, **_kwargs):
        raise urllib.error.URLError(cause)

    with pytest.raises(BoundedJsonHttpError) as caught:
        request_json(
            urllib.request.Request(URL + "/v1/health", method="GET"),
            timeout_seconds=5,
            replay_safe=False,
            opener=opener,
        )
    message = reach.describe(caught.value, URL, check_server_machine=False)
    assert message is not None
    return message


@pytest.mark.parametrize(
    "code,text,named",
    [
        (
            10061,
            "No connection could be made because the target machine actively refused it",
            reach.SERVER_REFUSED,
        ),
        (
            10060,
            "A connection attempt failed because the connected party did not "
            "properly respond after a period of time",
            reach.SERVER_TIMED_OUT,
        ),
        (11001, "No such host is known", reach.SERVER_NAME_UNRESOLVED),
        (11002, "This is usually a temporary error during hostname resolution", reach.SERVER_NAME_UNRESOLVED),
        (11004, "The requested name is valid, but no data of the requested type was found", reach.SERVER_NAME_UNRESOLVED),
        # Localized text carries no meaning; the code alone decides.
        (10061, "Es konnte keine Verbindung hergestellt werden", reach.SERVER_REFUSED),
        (10065, "A socket operation was attempted to an unreachable host", reach.SERVER_UNREACHABLE),
    ],
)
def test_windows_socket_errors_map_to_the_named_errors(code, text, named) -> None:
    assert _described(_winsock_error(code, text)).startswith(f"{named}: ")


def test_every_mapped_winsock_code_has_a_named_reason() -> None:
    reasons = set(network_failure_reason.WINSOCK_REASONS.values())
    assert reasons == {
        network_failure_reason.NETWORK_REFUSED,
        network_failure_reason.NETWORK_TIMED_OUT,
        network_failure_reason.NETWORK_NAME_UNRESOLVED,
    }


def test_clock_far_off_is_named_as_a_certificate_failure() -> None:
    error = ssl.SSLCertVerificationError(1, "certificate verify failed")
    error.verify_code = 9  # X509_V_ERR_CERT_NOT_YET_VALID
    error.verify_message = "certificate is not yet valid"
    message = _described(error)
    assert message.startswith(f"{reach.SERVER_HTTPS_FAILED}: ")
    assert "clock" in message
