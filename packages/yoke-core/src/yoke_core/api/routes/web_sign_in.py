"""Browser sign-in door: OIDC start/callback routes + the signed-out page.

``GET /v1/auth/oidc/start`` bounces the browser to the operator's OIDC
provider; ``GET /v1/auth/oidc/callback`` redeems the returned code,
verifies the id_token, walks the sign-in resolution ladder, mints a
web-session cookie, and lands the browser on the workbench at ``/``
(:mod:`yoke_core.api.routes.workbench`). The workbench shows
:func:`signed_out_page` to a browser without a valid session.

When OIDC config is absent these routes answer 409 and the workbench offers
API-token browser admission through ``yoke ui up``. What the web session
authorizes, and its CSRF protection, is :mod:`yoke_core.api.web_session_auth`.
"""

from __future__ import annotations

import html
import logging

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.routing import APIRouter

from yoke_core.api.http_auth import OIDC_CALLBACK_PATH, OIDC_START_PATH
from yoke_core.api.oidc_client import (
    OidcDiscoveryError,
    OidcExchangeError,
    OidcVerificationError,
    authorization_request_url,
    discover,
    exchange_code,
    verify_id_token,
)
from yoke_core.api.oidc_config import OidcConfigError, resolve_oidc_config
from yoke_core.api.oidc_flow_state import (
    FLOW_STATE_TTL_S,
    OidcFlowStateError,
    mint_flow_state,
    verify_flow_state,
)
from yoke_core.api.web_session_auth import WEB_SESSION_COOKIE_NAME
from yoke_core.domain import db_helpers
from yoke_core.domain.sign_in_resolution import resolve_sign_in
from yoke_core.domain.web_sessions import (
    DEFAULT_WEB_SESSION_TTL_S,
    mint_web_session,
)


_log = logging.getLogger("yoke.api.web_sign_in")

router = APIRouter()

#: Where a completed sign-in lands: the workbench root.
_SIGNED_IN_LANDING = "/"

#: Short-lived cookie carrying the signed state+nonce record between
#: start and callback. Scoped to the door's own path prefix.
FLOW_COOKIE_NAME = "yoke_oidc_flow"
_FLOW_COOKIE_PATH = "/v1/auth/oidc"

_V1_PREFIX = "/v1"
_START_SUBPATH = OIDC_START_PATH[len(_V1_PREFIX) :]
_CALLBACK_SUBPATH = OIDC_CALLBACK_PATH[len(_V1_PREFIX) :]


def _door_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": {"code": code, "message": message}},
    )


def _door_disabled() -> JSONResponse:
    return _door_error(
        409,
        "oidc_not_configured",
        "company sign-in is not configured on this server; set "
        "YOKE_OIDC_ISSUER, YOKE_OIDC_CLIENT_ID, "
        "YOKE_OIDC_CLIENT_SECRET_FILE, and YOKE_OIDC_REDIRECT_URL to "
        "enable it (see docs/self-host.md). For token browser sign-in, "
        "run `yoke ui up` on a connected CLI.",
    )


def _page(title: str, body_html: str, *, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        status_code=status_code,
        content=(
            "<!doctype html><html><head>"
            f'<meta charset="utf-8"><title>{html.escape(title)}</title>'
            "</head><body>"
            f"<h1>{html.escape(title)}</h1>{body_html}"
            "</body></html>"
        ),
    )


def _sign_in_error_page(status_code: int, title: str, detail: str) -> HTMLResponse:
    return _page(
        title,
        f"<p>{html.escape(detail)}</p>"
        f'<p><a href="{OIDC_START_PATH}">Restart sign-in</a></p>',
        status_code=status_code,
    )


@router.get(_START_SUBPATH)
def oidc_start() -> Response:
    """Bounce the browser to the provider's authorization endpoint."""
    try:
        config = resolve_oidc_config()
    except OidcConfigError as exc:
        return _door_error(409, "oidc_misconfigured", str(exc))
    if config is None:
        return _door_disabled()
    try:
        endpoints = discover(config.issuer)
    except OidcDiscoveryError as exc:
        return _door_error(502, "oidc_provider_unreachable", str(exc))
    flow = mint_flow_state(config)
    redirect = RedirectResponse(
        authorization_request_url(config, endpoints, flow),
        status_code=302,
    )
    redirect.set_cookie(
        FLOW_COOKIE_NAME,
        flow.cookie_value,
        max_age=FLOW_STATE_TTL_S,
        httponly=True,
        samesite="lax",
        secure=config.cookie_secure,
        path=_FLOW_COOKIE_PATH,
    )
    return redirect


@router.get(_CALLBACK_SUBPATH)
def oidc_callback(request: Request) -> Response:
    """Redeem the code, verify the id_token, resolve the actor, set the
    session cookie, and land on ``/``."""
    try:
        config = resolve_oidc_config()
    except OidcConfigError as exc:
        return _door_error(409, "oidc_misconfigured", str(exc))
    if config is None:
        return _door_disabled()

    params = request.query_params
    if params.get("error"):
        # Provider-reported failure (user cancelled, consent denied, ...).
        return _sign_in_error_page(
            400,
            "Sign-in did not complete",
            f"the identity provider reported: {params.get('error')}",
        )
    code = str(params.get("code") or "")
    state = str(params.get("state") or "")
    if not code or not state:
        return _sign_in_error_page(
            400,
            "Sign-in did not complete",
            "the callback is missing its code or state parameter",
        )
    try:
        nonce = verify_flow_state(
            config,
            cookie_value=str(request.cookies.get(FLOW_COOKIE_NAME) or ""),
            state_param=state,
        )
    except OidcFlowStateError:
        # One generic answer for missing/tampered/stale/mismatched state.
        return _sign_in_error_page(
            400,
            "Sign-in did not complete",
            "this sign-in attempt is stale or was not started by this browser",
        )
    try:
        endpoints = discover(config.issuer)
        token_response = exchange_code(config, endpoints, code=code)
    except (OidcDiscoveryError, OidcExchangeError) as exc:
        _log.warning("oidc_exchange_failed", extra={"context": {"detail": str(exc)}})
        return _sign_in_error_page(
            502,
            "Sign-in did not complete",
            "the identity provider could not be reached or refused the code exchange",
        )
    try:
        claims = verify_id_token(
            config,
            endpoints,
            id_token=str(token_response.get("id_token") or ""),
            nonce=nonce,
        )
    except OidcVerificationError:
        return _sign_in_error_page(
            401,
            "Sign-in did not complete",
            "id_token verification failed",
        )

    with db_helpers.connect() as conn:
        from yoke_core.api.frontend_events_config import verified_attribution

        try:
            acquisition = verified_attribution(request)
        except Exception:
            _log.warning(
                "attribution_unavailable: restore analytics capture; signing in without attribution",
                exc_info=True,
            )
            acquisition = None
        resolution = resolve_sign_in(
            conn,
            claims,
            allow_unverified_email=config.allow_unverified_email,
            attribution=acquisition,
        )
        if not resolution.succeeded or resolution.actor_id is None:
            return _sign_in_error_page(
                403,
                "Sign-in refused",
                resolution.detail,
            )
        session = mint_web_session(conn, actor_id=resolution.actor_id)

    redirect = RedirectResponse(_SIGNED_IN_LANDING, status_code=303)
    redirect.set_cookie(
        WEB_SESSION_COOKIE_NAME,
        session.raw_token,
        max_age=DEFAULT_WEB_SESSION_TTL_S,
        httponly=True,
        samesite="lax",
        secure=config.cookie_secure,
        path="/",
    )
    # Single-use flow state: without the cookie, a captured callback URL
    # cannot be replayed from another browser.
    redirect.delete_cookie(FLOW_COOKIE_NAME, path=_FLOW_COOKIE_PATH)
    return redirect


def signed_out_page() -> HTMLResponse:
    """The sign-in surface the workbench shows a browser without a session."""
    try:
        config = resolve_oidc_config()
    except OidcConfigError as exc:
        return _page(
            "Sign in to Yoke",
            "<p>Browser sign-in is misconfigured on this server: "
            f"{html.escape(str(exc))}. A server operator corrects the "
            "<code>YOKE_OIDC_*</code> settings as described in "
            "<code>docs/self-host-browser-sign-in.md</code>.</p>",
            status_code=503,
        )
    if config is not None:
        body = (
            f'<p><a href="{OIDC_START_PATH}">Sign in</a> with your '
            "organization's identity provider to open the workbench.</p>"
        )
    else:
        body = (
            "<p>Sign in with an API token through your CLI: run "
            "<code>yoke ui up</code> on a machine connected to this server. "
            "It opens a short-lived, single-use sign-in link for your actor. "
            "To connect first, run <code>yoke connect &lt;server-url&gt; "
            "--token-stdin</code> with your API token. Company sign-in is "
            "optional; see <code>docs/self-host-browser-sign-in.md</code>.</p>"
        )
    return _page("Sign in to Yoke", body)


__all__ = ["FLOW_COOKIE_NAME", "router", "signed_out_page"]
