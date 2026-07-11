"""Typed failures shared by GitHub REST transports."""

from __future__ import annotations


class RestTransportError(Exception):
    """Base class for terminal REST transport failures."""

    code: str = "rest_transport_error"

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class RestAuthError(RestTransportError):
    """HTTP 401 / 403 — token is missing, invalid, or lacks scope."""

    code = "rest_auth_error"


class RestNotFoundError(RestTransportError):
    """HTTP 404 — resource does not exist."""

    code = "rest_not_found"


class RestUnprocessableError(RestTransportError):
    """HTTP 422 — semantic validation failure."""

    code = "rest_unprocessable"


class RestServerError(RestTransportError):
    """HTTP 5xx that survived the retry budget."""

    code = "rest_server_error"


class RestNetworkError(RestTransportError):
    """Network / transport failure that survived the retry budget."""

    code = "rest_network_error"


class RestResponseTooLargeError(RestTransportError):
    """A GitHub REST response exceeded its parsing envelope."""

    code = "rest_response_too_large"


class RestResponseDecodeError(RestTransportError):
    """A GitHub REST response was not valid UTF-8."""

    code = "rest_response_decode_error"


class RateLimitedError(RestTransportError):
    """GitHub rate-limit (canonical 429 or secondary-limit 403)."""

    code = "rest_rate_limited"


__all__ = [
    "RateLimitedError",
    "RestAuthError",
    "RestNetworkError",
    "RestNotFoundError",
    "RestResponseDecodeError",
    "RestResponseTooLargeError",
    "RestServerError",
    "RestTransportError",
    "RestUnprocessableError",
]
