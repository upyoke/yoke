"""HTTP auth boundary for the Yoke FastAPI surface.

Two credentials, deliberately asymmetric:

* **Bearer API token** — the only credential accepted for function calls
  and every other mutating or non-allowlisted surface.
* **Web-session cookie** — minted by the browser sign-in door; accepted
  ONLY for the GET read surfaces named in :data:`WEB_SESSION_GET_PATHS`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.api_tokens import (
    TokenExpired,
    TokenNotFound,
    TokenRevoked,
    VerifiedToken,
    record_token_audit,
    verify_token,
)
from yoke_core.domain.web_sessions import WebSessionError, verify_web_session


AUTH_STATE_ATTR = "yoke_auth"

# Browser sign-in door surface. The start/callback pair is public by
# construction (they are how a browser acquires a credential); the
# landing page authenticates via the web-session cookie branch below.
LANDING_PATH = "/"
OIDC_START_PATH = "/v1/auth/oidc/start"
OIDC_CALLBACK_PATH = "/v1/auth/oidc/callback"

PUBLIC_PATHS = frozenset({"/v1/health", OIDC_START_PATH, OIDC_CALLBACK_PATH})

#: Name of the browser session cookie the sign-in door mints.
WEB_SESSION_COOKIE_NAME = "yoke_web_session"

#: GET paths where the web-session cookie is an accepted credential.
#:
#: CSRF rationale: a cookie is an ambient credential the browser attaches
#: to cross-site requests it did not intend. Accepting it only for
#: side-effect-free GET reads — and requiring the explicit Authorization
#: header (which browsers never attach automatically) for every write —
#: removes the forgeable-write surface structurally instead of managing
#: per-form CSRF tokens.
WEB_SESSION_GET_PATHS = frozenset({LANDING_PATH})

WEB_AUTH_STATE_ATTR = "yoke_web_auth"


@dataclass(frozen=True)
class HttpAuthContext:
    """Verified caller identity carried from middleware to route handlers."""

    token_id: int
    actor_id: int
    token_name: str


@dataclass(frozen=True)
class WebSessionAuthContext:
    """Verified browser identity (web-session cookie), read-only surfaces."""

    web_session_id: int
    actor_id: int


def is_public_path(path: str) -> bool:
    """Return True when ``path`` is intentionally public."""
    return path in PUBLIC_PATHS


def is_web_session_get_path(method: str, path: str) -> bool:
    """True when the web-session cookie is an accepted credential here."""
    return method.upper() == "GET" and path in WEB_SESSION_GET_PATHS


def authenticate_web_session(request: Request) -> Optional[WebSessionAuthContext]:
    """Verify the request's web-session cookie, or return ``None``.

    Every failure mode — no cookie, malformed value, unknown, revoked,
    expired, database unavailable — collapses to ``None`` so callers
    render one identical signed-out treatment and a probing client
    cannot learn whether a session record ever existed.
    """
    raw = str(request.cookies.get(WEB_SESSION_COOKIE_NAME) or "").strip()
    if not raw:
        return None
    try:
        with db_helpers.connect() as conn:
            verified = verify_web_session(conn, raw)
    except (ValueError, WebSessionError):
        return None
    except db_backend.database_error_types():
        return None
    return WebSessionAuthContext(
        web_session_id=verified.web_session_id,
        actor_id=verified.actor_id,
    )


def web_session_context(request: Request) -> Optional[WebSessionAuthContext]:
    """Return the verified web-session context stored by middleware, if any."""
    ctx = getattr(request.state, WEB_AUTH_STATE_ATTR, None)
    return ctx if isinstance(ctx, WebSessionAuthContext) else None


def auth_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    """Return a typed auth denial envelope."""
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
            },
        },
    )


def authenticate_request(request: Request) -> HttpAuthContext | JSONResponse:
    """Verify the request's bearer token or return a 401 denial response."""
    raw_header = request.headers.get("authorization") or ""
    if not raw_header:
        _record_failed_verify(request, "missing")
        return auth_error_response(
            status_code=401,
            code="authentication_required",
            message="missing Authorization: Bearer token",
        )
    scheme, separator, token = raw_header.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        _record_failed_verify(request, "malformed")
        return auth_error_response(
            status_code=401,
            code="authentication_malformed",
            message="Authorization header must use Bearer token syntax",
        )

    try:
        with db_helpers.connect() as conn:
            verified = verify_token(
                conn,
                token.strip(),
                diagnostic_metadata=_request_metadata(request),
            )
    except ValueError:
        _record_failed_verify(request, "malformed")
        return auth_error_response(
            status_code=401,
            code="authentication_malformed",
            message="API token has invalid syntax",
        )
    except TokenNotFound:
        return auth_error_response(
            status_code=401,
            code="authentication_unknown",
            message="API token is unknown",
        )
    except TokenRevoked:
        return auth_error_response(
            status_code=401,
            code="authentication_revoked",
            message="API token is revoked",
        )
    except TokenExpired:
        return auth_error_response(
            status_code=401,
            code="authentication_expired",
            message="API token is expired",
        )
    except db_backend.database_error_types() as exc:
        return auth_error_response(
            status_code=503,
            code="authentication_unavailable",
            message=f"token verification unavailable: {exc}",
        )

    return _context_from_verified(verified)


def require_auth_context(request: Request) -> HttpAuthContext:
    """Return the verified auth context stored by middleware."""
    ctx = getattr(request.state, AUTH_STATE_ATTR, None)
    if not isinstance(ctx, HttpAuthContext):
        raise RuntimeError("HTTP auth context missing from request state")
    return ctx


def bind_actor_from_auth(
    envelope: dict[str, Any],
    auth: HttpAuthContext,
) -> tuple[dict[str, Any], str | None]:
    """Return an envelope copy whose actor id is token-derived.

    The caller-supplied ``actor_id`` is not trusted. ``session_id`` stays in
    the envelope because claim/session gates still need the caller's harness
    context.
    """
    bound = dict(envelope)
    actor = bound.get("actor")
    ambient_session_id: str | None = None
    if isinstance(actor, dict):
        actor_copy = dict(actor)
        actor_copy["actor_id"] = str(auth.actor_id)
        session_id = actor_copy.get("session_id")
        if isinstance(session_id, str) and session_id:
            ambient_session_id = session_id
        bound["actor"] = actor_copy
    return bound, ambient_session_id


def record_function_authz(
    request: Request,
    auth: HttpAuthContext,
    *,
    function_id: str | None,
    request_id: str | None,
    project_id: int | None,
    permission_key: str | None,
    outcome: str,
) -> None:
    """Append non-secret function-call auth telemetry."""
    metadata = _request_metadata(request)
    if function_id:
        metadata["function_id"] = function_id
    if request_id:
        metadata["request_id"] = request_id
    try:
        with db_helpers.connect() as conn:
            record_token_audit(
                conn,
                api_token_id=auth.token_id,
                actor_id=auth.actor_id,
                project_id=project_id,
                event_type="function_authorize",
                outcome=outcome,
                permission_key=permission_key,
                diagnostic_metadata=metadata,
            )
    except db_backend.database_error_types():
        return


def _context_from_verified(verified: VerifiedToken) -> HttpAuthContext:
    return HttpAuthContext(
        token_id=verified.token_id,
        actor_id=verified.actor_id,
        token_name=verified.name,
    )


def _record_failed_verify(request: Request, outcome: str) -> None:
    try:
        with db_helpers.connect() as conn:
            record_token_audit(
                conn,
                api_token_id=None,
                actor_id=None,
                event_type="verify",
                outcome=outcome,
                diagnostic_metadata=_request_metadata(request),
            )
    except db_backend.database_error_types():
        return


def _request_metadata(request: Request) -> dict[str, Any]:
    return {
        "method": request.method,
        "path": request.url.path,
        "request_id": request.headers.get("x-request-id"),
    }


__all__ = [
    "AUTH_STATE_ATTR",
    "HttpAuthContext",
    "LANDING_PATH",
    "OIDC_CALLBACK_PATH",
    "OIDC_START_PATH",
    "WEB_AUTH_STATE_ATTR",
    "WEB_SESSION_COOKIE_NAME",
    "WEB_SESSION_GET_PATHS",
    "WebSessionAuthContext",
    "auth_error_response",
    "authenticate_request",
    "authenticate_web_session",
    "bind_actor_from_auth",
    "is_public_path",
    "is_web_session_get_path",
    "record_function_authz",
    "require_auth_context",
    "web_session_context",
]
