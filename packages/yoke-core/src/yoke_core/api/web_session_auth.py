"""Browser web-session credential for the Yoke server.

The browser sign-in door (:mod:`yoke_core.api.routes.web_sign_in`) mints a
``yoke_web_session`` cookie. That cookie admits the workbench pages
(:mod:`yoke_core.api.routes.workbench`) and authorizes
``POST /v1/functions/call`` as the session's actor, so a signed-in browser
reads and writes exactly as the workbench does on Local and Cloud. The
engine's permission model is the enforcement; there is no browser-specific
function allowlist.

CSRF protection is the same pair Cloud's same-origin relay applies: the
cookie is ``SameSite=Lax``, so browsers do not attach it to cross-site
POSTs, and every cookie-authorized function call must also pass
:func:`cross_origin_refusal`. A request carrying an ``Authorization``
header takes the bearer path in :mod:`yoke_core.api.http_auth` instead,
whatever cookies ride along.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

from yoke_core.api.http_auth import auth_error_response
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.actor_state import ActorDisabledError
from yoke_core.domain.web_sessions import WebSessionError, verify_web_session

#: Name of the browser session cookie the sign-in door mints.
WEB_SESSION_COOKIE_NAME = "yoke_web_session"

#: The one API path a web-session cookie authorizes.
WEB_SESSION_FUNCTION_CALL_PATH = "/v1/functions/call"

#: Request-state attribute carrying the verified browser identity.
WEB_AUTH_STATE_ATTR = "yoke_web_auth"

#: ``Sec-Fetch-Site`` values a same-origin browser request may carry.
_SAME_ORIGIN_FETCH_SITES = frozenset({"same-origin", "none"})

_SIGN_IN_AGAIN = "reload this server's workbench page and sign in again"


@dataclass(frozen=True)
class WebSessionAuthContext:
    """Verified browser identity (web-session cookie)."""

    web_session_id: int
    actor_id: int


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
    except (ValueError, WebSessionError, ActorDisabledError):
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


def is_web_session_function_call(request: Request) -> bool:
    """True for a cookie-carrying function call with no bearer header."""
    return (
        request.method.upper() == "POST"
        and request.url.path == WEB_SESSION_FUNCTION_CALL_PATH
        and not request.headers.get("authorization")
        and bool(request.cookies.get(WEB_SESSION_COOKIE_NAME))
    )


def cross_origin_refusal(request: Request) -> Optional[JSONResponse]:
    """Refuse a cross-site request; ``None`` when it may proceed.

    Each rule applies only when its header is present, as on Cloud's
    relay: ``Sec-Fetch-Site`` must be ``same-origin`` or ``none``, and
    ``Origin`` must name this server's own host. A declared trusted
    transport proxy may supply the external host through ``X-Forwarded-Host``;
    the server middleware normalizes it into ``Host`` before this check.
    Raw forwarding headers never authorize an origin. ``Origin: null`` is refused.
    """
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site and fetch_site not in _SAME_ORIGIN_FETCH_SITES:
        return _cross_origin(f"Sec-Fetch-Site is {fetch_site!r}")
    origin = request.headers.get("origin")
    if origin is None:
        return None
    origin_host = urlsplit(origin).netloc if origin != "null" else ""
    server_host = request.headers.get("host") or request.url.netloc
    if not origin_host or origin_host != server_host:
        return _cross_origin(f"Origin {origin!r} is not this server ({server_host!r})")
    return None


def authenticate_web_session_function_call(
    request: Request,
) -> WebSessionAuthContext | JSONResponse:
    """Admit a browser function call, or return its named refusal."""
    refusal = cross_origin_refusal(request)
    if refusal is not None:
        return refusal
    web_auth = authenticate_web_session(request)
    if web_auth is None:
        return auth_error_response(
            status_code=401,
            code="web_session_invalid",
            message=(
                "this browser session is expired, revoked, or unknown; "
                f"{_SIGN_IN_AGAIN}"
            ),
        )
    return web_auth


def _cross_origin(detail: str) -> JSONResponse:
    return auth_error_response(
        status_code=403,
        code="cross_origin_refused",
        message=(
            f"a browser-session function call must be same-origin: {detail}. "
            "Call from the workbench page this server served, or send an "
            "API token as Authorization: Bearer"
        ),
    )


__all__ = [
    "WEB_AUTH_STATE_ATTR",
    "WEB_SESSION_COOKIE_NAME",
    "WEB_SESSION_FUNCTION_CALL_PATH",
    "WebSessionAuthContext",
    "authenticate_web_session",
    "authenticate_web_session_function_call",
    "cross_origin_refusal",
    "is_web_session_function_call",
    "web_session_context",
]
