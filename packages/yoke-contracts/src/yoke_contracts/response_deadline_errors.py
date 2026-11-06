"""Typed failures shared by whole-open deadline transports."""

from __future__ import annotations


class ResponseOpenError(OSError):
    """An HTTPS response could not be opened safely."""


class ResponseOpenDeadlineError(ResponseOpenError, TimeoutError):
    """An HTTPS open did not finish before its absolute deadline."""


class ResponseHeadersDeadlineError(ResponseOpenDeadlineError):
    """The request was sent, but its response did not arrive before the deadline.

    Unlike a DNS, connect or TLS deadline, the server may already be running
    the request, so a caller must not treat this as an unreached server.
    """


__all__ = [
    "ResponseHeadersDeadlineError",
    "ResponseOpenDeadlineError",
    "ResponseOpenError",
]
