"""Classify why a network request failed, on every operating system.

Python already raises ``socket.gaierror``, ``ConnectionRefusedError`` and
``TimeoutError`` for most Windows socket failures. Some paths (a proxy
tunnel, a re-raised ``OSError``) carry only the Windows Sockets code and its
localized text, such as "No connection could be made because the target
machine actively refused it". Those codes map to the same named reasons, so
a Windows client sees the same ``server_refused`` or ``server_timed_out``
as a Mac or Linux one, whatever language its error text is in.
"""

from __future__ import annotations

import errno
import http.client
import socket
import ssl

NETWORK_NAME_UNRESOLVED = "name_unresolved"
NETWORK_REFUSED = "refused"
NETWORK_TIMED_OUT = "timed_out"
NETWORK_TLS = "tls"
NETWORK_NOT_HTTP = "not_http"
NETWORK_UNREACHABLE = "unreachable"

#: Windows Sockets error codes (``OSError.winerror``) and their reasons.
#: https://learn.microsoft.com/windows/win32/winsock/windows-sockets-error-codes-2
WINSOCK_REASONS = {
    10060: NETWORK_TIMED_OUT,  # WSAETIMEDOUT
    10061: NETWORK_REFUSED,  # WSAECONNREFUSED
    11001: NETWORK_NAME_UNRESOLVED,  # WSAHOST_NOT_FOUND
    11002: NETWORK_NAME_UNRESOLVED,  # WSATRY_AGAIN
    11003: NETWORK_NAME_UNRESOLVED,  # WSANO_RECOVERY
    11004: NETWORK_NAME_UNRESOLVED,  # WSANO_DATA
}
_ERRNO_REASONS = {
    errno.ECONNREFUSED: NETWORK_REFUSED,
    errno.ETIMEDOUT: NETWORK_TIMED_OUT,
}


def network_reason(cause: BaseException) -> str:
    """Return the named reason for one network failure."""
    if isinstance(cause, socket.gaierror):
        return NETWORK_NAME_UNRESOLVED
    if isinstance(cause, ConnectionRefusedError):
        return NETWORK_REFUSED
    if isinstance(cause, TimeoutError):
        return NETWORK_TIMED_OUT
    if isinstance(cause, ssl.SSLError):
        return NETWORK_TLS
    if isinstance(cause, http.client.HTTPException):
        return NETWORK_NOT_HTTP
    winerror = getattr(cause, "winerror", None)
    if winerror in WINSOCK_REASONS:
        return WINSOCK_REASONS[winerror]
    if isinstance(cause, OSError) and cause.errno in _ERRNO_REASONS:
        return _ERRNO_REASONS[cause.errno]
    return NETWORK_UNREACHABLE


__all__ = [
    "NETWORK_NAME_UNRESOLVED",
    "NETWORK_NOT_HTTP",
    "NETWORK_REFUSED",
    "NETWORK_TIMED_OUT",
    "NETWORK_TLS",
    "NETWORK_UNREACHABLE",
    "WINSOCK_REASONS",
    "network_reason",
]
