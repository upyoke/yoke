"""Token-gated web view of the machine-local universe.

A deliberately small FastAPI app, separate from the main Yoke API
(:mod:`yoke_core.api.app_factory`): the main API authenticates DB-issued
bearer tokens for remote clients, while this server is a loopback-only
window into the universe the machine already holds. Reads dispatch
in-process through :func:`yoke_core.domain.yoke_function_dispatch.dispatch`
— the same product path every non-https ``yoke`` CLI call uses.

Security model:

* Binds ``127.0.0.1`` only; nothing is reachable off-machine.
* One random session token per run (:func:`mint_session_token`). Every
  route — the app shell, static assets, and the function proxy — requires
  it. The token arrives as a ``?token=`` query parameter on the first hit;
  the app shell exchanges it for an HttpOnly cookie and 303-redirects to
  the bare URL, so asset and API requests authenticate via the cookie and
  the tokened form drops out of browser history. The tokened URL is the
  user's door: print it to the caller's terminal, never into event
  streams or logs.
* The function proxy accepts only the function ids in
  :data:`UI_READ_FUNCTION_ALLOWLIST` — a closed, read-only roster.
  Everything else is refused with 403 before the dispatcher sees it.
"""

from __future__ import annotations

import secrets
import socket
import threading
import uuid
import webbrowser
from typing import Any, Dict, Optional

#: Default bind host and TCP port for the UI server (loopback only).
#: Collision-probed at startup; ``--host`` and ``--port`` on ``yoke ui``
#: override within the same loopback-only security boundary.
DEFAULT_UI_HOST = "127.0.0.1"
DEFAULT_UI_PORT = 8688
LOOPBACK_UI_HOSTS = frozenset({"127.0.0.1", "localhost"})

#: ``secrets.token_urlsafe`` byte length for the per-run session token.
SESSION_TOKEN_BYTES = 32

#: Cookie the app-shell response sets so assets/API ride the session.
SESSION_COOKIE_NAME = "yoke_ui_session"

#: The closed roster of function ids the browser proxy may dispatch.
#: Read-only by construction: every id here is registered with no side
#: effects and no claim requirement.
UI_READ_FUNCTION_ALLOWLIST = frozenset({
    "organizations.get",
    "projects.list",
    "items.get.run",
    "items.list.run",
    "epic_tasks.list.run",
    "strategy.doc.list",
    "ouroboros.entry.list",
    "board.data.get",
    "deployment_runs.list",
    "sessions.list",
    "frontier.list",
    "events.query.run",
})

#: Packaged static assets the server may serve, with their content types.
#: A closed name→type map (no filesystem paths from the request) keeps
#: traversal structurally impossible.
ASSET_CONTENT_TYPES: Dict[str, str] = {
    "index.html": "text/html; charset=utf-8",
    # Developer page, not a product route: mounts the same app with sample
    # platform chrome shaped like the hosted shell's slots, so frame defects
    # that only show with occupied slots are visible on a laptop.
    "hosted-frame-harness.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "contract.js": "text/javascript; charset=utf-8",
    "contract-version.js": "text/javascript; charset=utf-8",
    "mount-options.js": "text/javascript; charset=utf-8",
    "universe_navigation.js": "text/javascript; charset=utf-8",
    "universe_views.js": "text/javascript; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "shell.css": "text/css; charset=utf-8",
    "theme.css": "text/css; charset=utf-8",
    "yoke.svg": "image/svg+xml",
    "yoke-wordmark.svg": "image/svg+xml",
    "favicon.svg": "image/svg+xml",
    "favicon.ico": "image/x-icon",
    "apple-touch-icon.png": "image/png",
}

_BROWSER_OPEN_DELAY_S = 0.5


class UiServerError(RuntimeError):
    """The UI server could not be prepared or started."""


def mint_session_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def _token_matches(candidate: str, token: str) -> bool:
    """Constant-time token comparison.

    Byte-wise on purpose: ``secrets.compare_digest`` raises ``TypeError``
    on non-ASCII ``str`` input, and a hostile/garbled candidate must land
    on the clean 401 path, never a 500.
    """
    return secrets.compare_digest(
        candidate.encode("utf-8"), token.encode("utf-8"),
    )


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


def _asset_bytes(asset_name: str) -> bytes:
    from importlib.resources import files

    return files(__package__).joinpath("static", asset_name).read_bytes()


def create_ui_app(token: str):
    """Build the FastAPI app; every route requires the session token."""
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import (
        HTMLResponse,
        JSONResponse,
        RedirectResponse,
        Response,
    )

    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain.yoke_function_dispatch import dispatch

    if not token:
        raise UiServerError("a non-empty session token is required")

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def session_token_gate(request, call_next):
        candidate = (
            request.query_params.get("token")
            or request.cookies.get(SESSION_COOKIE_NAME)
            or ""
        )
        if not _token_matches(candidate, token):
            return JSONResponse(
                {"error": {
                    "code": "session_token_required",
                    "message": (
                        "this UI server admits only the per-run session "
                        "token printed by `yoke ui`"
                    ),
                }},
                status_code=401,
            )
        return await call_next(request)

    @app.get("/")
    def app_shell(
        # NOTE: parameter annotations here must resolve from module globals
        # (postponed annotations + FastAPI's type-hint resolution); a
        # locally-imported type like Request silently degrades to a query
        # parameter and breaks the route with a 422.
        query_token: Optional[str] = Query(default=None, alias="token"),
    ) -> Response:
        if query_token and _token_matches(query_token, token):
            # Exchange the query token for an HttpOnly cookie and bounce
            # to the bare URL: the cookie authenticates the follow-up
            # request, and the tokened URL drops out of browser history.
            redirect: Response = RedirectResponse(url="/", status_code=303)
            redirect.set_cookie(
                SESSION_COOKIE_NAME, token,
                httponly=True, samesite="strict",
            )
            return redirect
        # No (valid) query token here means the session cookie admitted
        # the request through the gate; serve the shell directly.
        return HTMLResponse(_asset_bytes("index.html").decode("utf-8"))

    @app.get("/assets/{asset_name}")
    def asset(asset_name: str) -> Response:
        content_type = ASSET_CONTENT_TYPES.get(asset_name)
        if content_type is None:
            raise HTTPException(status_code=404, detail="unknown asset")
        return Response(_asset_bytes(asset_name), media_type=content_type)

    @app.post("/api/functions/call")
    def call_function(envelope: Dict[str, Any]) -> JSONResponse:
        function_id = str(envelope.get("function") or "")
        if function_id not in UI_READ_FUNCTION_ALLOWLIST:
            return JSONResponse(
                {"error": {
                    "code": "function_not_allowed",
                    "message": (
                        f"function {function_id!r} is not on this UI "
                        "server's read-only allowlist"
                    ),
                    "allowed": sorted(UI_READ_FUNCTION_ALLOWLIST),
                }},
                status_code=403,
            )
        raw_target = envelope.get("target")
        try:
            target = (
                TargetRef(**raw_target)
                if isinstance(raw_target, dict)
                else TargetRef(kind="global")
            )
        except Exception as exc:
            return JSONResponse(
                {"error": {"code": "target_invalid", "message": str(exc)}},
                status_code=422,
            )
        request = FunctionCallRequest(
            function=function_id,
            # No harness session exists in a browser: the empty session id
            # (with ambient resolution pinned off below) is the anonymous
            # local-read identity, same as an unbound CLI read.
            actor=ActorContext(actor_id=None, session_id=""),
            target=target,
            request_id=str(envelope.get("request_id") or uuid.uuid4()),
            payload=dict(envelope.get("payload") or {}),
            options=dict(envelope.get("options") or {}),
        )
        # ambient_session_id="" (never None): the browser's identity lives
        # client-side, so the dispatcher must not resolve the SERVER
        # process's env/ancestry into a session.
        response = dispatch(request, ambient_session_id="")
        return JSONResponse(response.model_dump(mode="json"))

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
    app = create_ui_app(token)
    if open_browser:
        opener = threading.Timer(
            _BROWSER_OPEN_DELAY_S,
            webbrowser.open,
            [private_url(port, token, host=bind_host)],
        )
        opener.daemon = True
        opener.start()
    uvicorn.run(app, host=bind_host, port=port, log_level="warning")


__all__ = [
    "ASSET_CONTENT_TYPES",
    "DEFAULT_UI_PORT",
    "SESSION_COOKIE_NAME",
    "SESSION_TOKEN_BYTES",
    "UI_READ_FUNCTION_ALLOWLIST",
    "UiServerError",
    "create_ui_app",
    "mint_session_token",
    "private_url",
    "resolve_ui_port",
    "serve_ui",
]
