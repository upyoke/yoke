"""Token-gated web view of the machine-local universe.

A deliberately small FastAPI app, separate from the main Yoke API
(:mod:`yoke_core.api.app_factory`): the main API authenticates DB-issued
bearer tokens for remote clients, while this server is a loopback-only
window into the universe the machine already holds. Reads dispatch
in-process through :func:`yoke_core.domain.yoke_function_dispatch.dispatch`
— the same product path every non-https ``yoke`` CLI call uses.

Security model:

* Binds ``127.0.0.1`` only; nothing is reachable off-machine.
* Serves only a connection this machine reads directly
  (:mod:`yoke_core.ui.served_universe_connection`); an https or
  prod-flagged binding refuses at startup rather than answering from a
  universe the page does not name.
* One random session token per run, minted and compared by
  :mod:`yoke_core.ui.session_gate`. ``/served-build`` is public so a
  pre-merge identity proof can read the commit before it holds that
  token, as the self-hosted workbench already does. Every other
  workbench route requires the token. The anonymous analytics collector separately
  enforces its exact origin, publishable key, and shared rate budget.
  The token arrives as a ``?token=`` query parameter on the first hit;
  the app shell exchanges it for an HttpOnly cookie and 303-redirects to
  the bare URL, so asset and API requests authenticate via the cookie and
  the tokened form drops out of browser history. That cookie is named
  after the bind port (:func:`~yoke_core.ui.session_gate.session_cookie_name`),
  because cookies are not port-scoped. Print the door URL only to the terminal.
* The function proxy accepts only the function ids in
  :data:`UI_READ_FUNCTION_ALLOWLIST` — a closed, read-only roster — plus
  the two actor-scoped Overview dismissal writes in
  :data:`UI_MUTATION_FUNCTION_ALLOWLIST`, which act only as the resolved
  local operator actor. Everything else is refused with 403 before the
  dispatcher sees it.
"""

from __future__ import annotations

import socket
import threading
import webbrowser
from urllib.parse import urlencode
from starlette.requests import Request
from yoke_core.ui.dashboard_routes import is_dashboard_path
from typing import Any, Dict, Optional

from yoke_contracts.runtime_identity import PORTABILITY_LOCAL, SERVED_BUILD_PATH
from yoke_cli.config.hosted_machine_browser import open_url
from yoke_core.ui.asset_roster import ASSET_CACHE_CONTROL, ASSET_CONTENT_TYPES
from yoke_core.ui.function_proxy import (
    UI_ACTIVATION_LATCH_FUNCTIONS,
    UI_MUTATION_FUNCTION_ALLOWLIST,
    UI_READ_FUNCTION_ALLOWLIST,
    proxy_function_call,
)
from yoke_core.ui.served_source_identity import (
    served_build_identity,
    served_install,
)
from yoke_core.ui.served_universe_connection import (
    environment_display_label,
    serving_connection,
)
from yoke_core.ui.session_gate import (
    SESSION_COOKIE_PREFIX,
    SESSION_TOKEN_BYTES,
    mint_session_token,
    session_cookie_name,
    token_matches,
)
from yoke_core.ui.workbench_shell import (
    asset_response,
    host_packet,
    served_build_response,
    shell_response,
)

#: Default bind host and TCP port for the UI server (loopback only).
#: Collision-probed at startup; ``--host`` and ``--port`` on ``yoke ui``
#: override within the same loopback-only security boundary.
DEFAULT_UI_HOST = "127.0.0.1"
DEFAULT_UI_PORT = 8688
LOOPBACK_UI_HOSTS = frozenset({"127.0.0.1", "localhost"})

_BROWSER_OPEN_DELAY_S = 0.5


class UiServerError(RuntimeError):
    """The UI server could not be prepared or started."""


def resolve_ui_host(requested: Optional[str] = None) -> str:
    """Return a loopback bind host, refusing remote-facing addresses."""
    host = DEFAULT_UI_HOST if requested is None else str(requested).strip()
    if host not in LOOPBACK_UI_HOSTS:
        raise UiServerError(
            f"host must be loopback-only ({', '.join(sorted(LOOPBACK_UI_HOSTS))}), "
            f"got {host!r}"
        )
    return host


def resolve_ui_port(
    requested: Optional[int] = None,
    *,
    host: str = DEFAULT_UI_HOST,
) -> int:
    """Return a usable loopback port, probing for collisions.

    Mirrors the local-core launcher's socket probe: bind-test the port and
    refuse with guidance naming ``--port`` when it is already in use.
    """
    port = DEFAULT_UI_PORT if requested is None else int(requested)
    if not 1 <= port <= 65535:
        raise UiServerError(f"port must be between 1 and 65535, got {port}")
    bind_host = resolve_ui_host(host)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((bind_host, port))
        except OSError as exc:
            raise UiServerError(
                f"port {port} is already in use on {bind_host} ({exc}); "
                "pick another with --port"
            ) from exc
    return port


def private_url(
    port: int,
    token: str,
    *,
    host: str = DEFAULT_UI_HOST,
) -> str:
    """The tokened URL that admits the caller — terminal-only, never logged."""
    return f"http://{resolve_ui_host(host)}:{port}/?token={token}"


#: The Local view's host capabilities: a local universe trivially has its
#: machine connected, so this host — not the engine — supplies that fact.
_LOCAL_CAPABILITIES = {
    "data": {
        "portability": {"mode": "local", "sectionOwned": False},
        "onboarding": {"machineConnected": True},
    },
}


def _local_operator_actor_id() -> Optional[int]:
    from yoke_core.ui.local_operator_actor import resolve_local_operator_actor

    try:
        return resolve_local_operator_actor()
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "local_operator_actor_unavailable: the topbar actor identity "
            "will not resolve; restore the local universe connection and "
            "reload",
            exc_info=True,
        )
        return None


def _local_host_packet(environment: str) -> Dict[str, Any]:
    """The Local view's mount packet, from the canonical runtime identity."""
    return host_packet(
        portability_mode=PORTABILITY_LOCAL,
        install=served_install(),
        build=served_build_identity(),
        environment_label=environment_display_label(environment),
        current_actor_id=_local_operator_actor_id(),
        capabilities=_LOCAL_CAPABILITIES,
    )


def create_ui_app(token: str, *, port: int = DEFAULT_UI_PORT):
    """Build the loopback app with port-scoped workbench session cookies."""
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import JSONResponse, RedirectResponse, Response

    if not token:
        raise UiServerError("a non-empty session token is required")
    # Checked here rather than only in the command that starts a daemon:
    # importing this module is enough to serve a view, so a guard the
    # caller can skip is a guard that will be skipped.
    environment, refusal = serving_connection()
    if refusal is not None:
        raise UiServerError(refusal)
    cookie_name = session_cookie_name(port)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    from yoke_core.api.routes.frontend_events import router as events_router

    app.include_router(events_router)

    @app.middleware("http")
    async def session_token_gate(request, call_next):
        from yoke_core.api.frontend_events_config import COLLECTOR_PATHS

        # /served-build is the commit this process serves. Browser QA reads
        # it with the run's own session or with none, before that cookie
        # exists. Every other route stays behind the per-run token.
        if request.url.path in COLLECTOR_PATHS or request.url.path == SERVED_BUILD_PATH:
            return await call_next(request)
        candidate = (
            request.query_params.get("token") or request.cookies.get(cookie_name) or ""
        )
        if not token_matches(candidate, token):
            return JSONResponse(
                {
                    "error": {
                        "code": "session_token_required",
                        "message": (
                            "this UI server admits only the per-run session "
                            "token printed by `yoke ui`"
                        ),
                    }
                },
                status_code=401,
            )
        return await call_next(request)

    @app.get("/")
    def app_shell(
        request: Request,
        query_token: Optional[str] = Query(default=None, alias="token"),
    ) -> Response:
        if not is_dashboard_path(request.url.path):
            raise HTTPException(status_code=404, detail="unknown dashboard route")
        if query_token and token_matches(query_token, token):
            # Exchange the query token for an HttpOnly cookie and bounce
            # to the bare URL: the cookie authenticates the follow-up
            # request, and the tokened URL drops out of browser history.
            query = urlencode(
                [
                    (key, value)
                    for key, value in request.query_params.multi_items()
                    if key != "token"
                ]
            )
            url = request.url.path + (f"?{query}" if query else "")
            redirect: Response = RedirectResponse(url=url, status_code=303)
            redirect.set_cookie(
                cookie_name,
                token,
                httponly=True,
                samesite="strict",
            )
            return redirect
        # No (valid) query token here means the session cookie admitted
        # the request through the gate; serve the shell directly.
        return shell_response(_local_host_packet(environment))

    @app.get("/assets/{asset_name}")
    def asset(asset_name: str) -> Response:
        return asset_response(asset_name)

    @app.get(SERVED_BUILD_PATH)
    def served_build_path() -> Response:
        return served_build_response(served_build_identity())

    @app.post("/api/functions/call")
    def call_function(envelope: Dict[str, Any]) -> JSONResponse:
        payload, status_code = proxy_function_call(envelope)
        return JSONResponse(payload, status_code=status_code)

    app.get("/{path:path}")(app_shell)
    return app


def serve_ui(
    *,
    port: int,
    token: str,
    open_browser: bool = True,
    host: str = DEFAULT_UI_HOST,
) -> None:
    """Run the UI server until interrupted (blocking).

    ``open_browser=True`` opens the tokened URL in the default browser
    shortly after startup begins; the URL itself stays terminal-only.
    """
    import uvicorn

    bind_host = resolve_ui_host(host)
    app = create_ui_app(token, port=port)
    if open_browser:
        opener = threading.Timer(
            _BROWSER_OPEN_DELAY_S,
            lambda url: open_url(url, browser_open=webbrowser.open),
            [private_url(port, token, host=bind_host)],
        )
        opener.daemon = True
        opener.start()
    uvicorn.run(app, host=bind_host, port=port, log_level="warning")


__all__ = [
    "ASSET_CACHE_CONTROL",
    "ASSET_CONTENT_TYPES",
    "DEFAULT_UI_PORT",
    "SESSION_COOKIE_PREFIX",
    "SESSION_TOKEN_BYTES",
    "UI_ACTIVATION_LATCH_FUNCTIONS",
    "UI_MUTATION_FUNCTION_ALLOWLIST",
    "UI_READ_FUNCTION_ALLOWLIST",
    "UiServerError",
    "create_ui_app",
    "mint_session_token",
    "private_url",
    "resolve_ui_port",
    "serve_ui",
    "session_cookie_name",
]
