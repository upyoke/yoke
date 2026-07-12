"""Typed failures shared by whole-open deadline transports."""

from __future__ import annotations


class ResponseOpenError(OSError):
    """An HTTPS response could not be opened safely."""


class ResponseOpenDeadlineError(ResponseOpenError, TimeoutError):
    """An HTTPS open did not finish before its absolute deadline."""


__all__ = ["ResponseOpenDeadlineError", "ResponseOpenError"]
