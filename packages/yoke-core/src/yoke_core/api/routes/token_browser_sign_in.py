"""Exchange a bearer credential for single-use browser admission.

The code travels in a URL fragment, then a same-origin POST body: access logs,
HTTP referrers, and the server's request telemetry never receive it in a URL.
Company sign-in disables this door and retains its own admission ladder.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field

from yoke_contracts.browser_sign_in import (
    BROWSER_SIGN_IN_PATH,
    BROWSER_SIGN_IN_REDEEM_PATH,
    BROWSER_SIGN_IN_MAX_LENGTH,
)
from yoke_core.api.http_auth import auth_error_response, require_auth_context
from yoke_core.api.oidc_config import OidcConfigError, resolve_oidc_config
from yoke_core.api.web_session_auth import WEB_SESSION_COOKIE_NAME, cross_origin_refusal
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.actor_state import ActorDisabledError
from yoke_core.domain.browser_sign_in_links import (
    BROWSER_SIGN_IN_TTL_S,
    BrowserSignInError,
    mint_browser_sign_in_link,
    redeem_browser_sign_in_link,
)
from yoke_core.domain.web_sessions import DEFAULT_WEB_SESSION_TTL_S

router = APIRouter()
_PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_EXCHANGE = BROWSER_SIGN_IN_PATH.removeprefix("/v1")
_REDEEM = BROWSER_SIGN_IN_REDEEM_PATH.removeprefix("/v1")


def _error(code: str, message: str, status: int = 409) -> JSONResponse:
    response = auth_error_response(status_code=status, code=code, message=message)
    response.headers.update(_PRIVATE_HEADERS)
    return response


def _token_door_refusal() -> Response | None:
    try:
        config = resolve_oidc_config()
    except OidcConfigError as exc:
        return _error(
            "oidc_misconfigured",
            f"{exc}; ask the server operator to repair OIDC settings",
        )
    if config is not None:
        return _error(
            "browser_sign_in_oidc_required",
            "Company sign-in is configured; open this server's workbench and sign in there",
        )
    return None


@router.post(_EXCHANGE)
def exchange(request: Request) -> Response:
    auth = require_auth_context(request)
    try:
        config = resolve_oidc_config()
    except OidcConfigError as exc:
        return _error(
            "oidc_misconfigured",
            f"{exc}; ask the server operator to repair OIDC settings",
        )
    if config is not None:
        return JSONResponse(
            {"auth_method": "oidc", "sign_in_path": "/"}, headers=_PRIVATE_HEADERS
        )
    try:
        with db_helpers.connect() as conn:
            code = mint_browser_sign_in_link(conn, actor_id=auth.actor_id)
    except ActorDisabledError as exc:
        return _error("actor_disabled", str(exc), 403)
    except db_backend.database_error_types():
        return _error(
            "browser_sign_in_unavailable",
            "Sign-in storage is unavailable; ask the server operator to restore database service, then run `yoke ui up` again",
            503,
        )
    return JSONResponse(
        {
            "auth_method": "token",
            "sign_in_path": BROWSER_SIGN_IN_REDEEM_PATH + "#" + code,
            "expires_in": BROWSER_SIGN_IN_TTL_S,
        },
        headers=_PRIVATE_HEADERS,
    )


@router.get(_EXCHANGE)
def sign_in_method() -> Response:
    """Discover company sign-in before requiring an API credential."""
    try:
        config = resolve_oidc_config()
    except OidcConfigError as exc:
        return _error(
            "oidc_misconfigured",
            f"{exc}; ask the server operator to repair OIDC settings",
        )
    return JSONResponse(
        {"auth_method": "oidc" if config is not None else "token"},
        headers=_PRIVATE_HEADERS,
    )


@router.get(_REDEEM)
def admission_page() -> Response:
    refusal = _token_door_refusal()
    if refusal is not None:
        return refusal
    return HTMLResponse(
        """<!doctype html><html><head><meta charset="utf-8">
<title>Sign in to Yoke</title></head><body>
<h1>Sign in to Yoke</h1><p id="status">Signing in…</p>
<noscript>Enable JavaScript, then run <code>yoke ui up</code> again.</noscript>
<script>
const code = location.hash.slice(1);
history.replaceState(null, '', location.pathname);
(async () => {
  try {
    const response = await fetch(location.pathname, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code}), credentials: 'same-origin'
    });
    const result = await response.json();
    if (!response.ok) {
      document.getElementById('status').textContent =
        result.error.code + ': ' + result.error.message;
      return;
    }
    location.replace('/');
  } catch (_) {
    document.getElementById('status').textContent =
      'browser_sign_in_unavailable: run `yoke ui up` again; if it persists, ask the server operator to restore service';
  }
})();
</script></body></html>""",
        headers=_PRIVATE_HEADERS,
    )


class AdmissionCode(BaseModel):
    code: str = Field(max_length=BROWSER_SIGN_IN_MAX_LENGTH)


@router.post(_REDEEM)
def redeem(request: Request, body: AdmissionCode) -> Response:
    refusal = _token_door_refusal() or cross_origin_refusal(request)
    if refusal is not None:
        return refusal
    try:
        with db_helpers.connect() as conn:
            session = redeem_browser_sign_in_link(conn, body.code)
    except BrowserSignInError as exc:
        return _error(exc.code, str(exc), 401)
    except ActorDisabledError as exc:
        return _error("actor_disabled", str(exc), 403)
    except db_backend.database_error_types():
        return _error(
            "browser_sign_in_unavailable",
            "Sign-in storage is unavailable; ask the server operator to restore database service, then run `yoke ui up` again",
            503,
        )
    response = JSONResponse({"success": True}, headers=_PRIVATE_HEADERS)
    response.set_cookie(
        WEB_SESSION_COOKIE_NAME,
        session.raw_token,
        max_age=DEFAULT_WEB_SESSION_TTL_S,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return response
