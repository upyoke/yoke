"""The universe workbench, served by the Yoke server itself.

A self-hosted server serves the same workbench Local and Cloud serve: the
shell at ``/`` and every dashboard deep path
(:func:`yoke_core.ui.dashboard_routes.is_dashboard_path`), the asset roster
under ``/assets/``, and the served-build identity at ``/served-build``. The
serving bytes are shared with the Local view through
:mod:`yoke_core.ui.workbench_shell`.

A signed-in browser (web-session cookie, see
:mod:`yoke_core.api.web_session_auth`) gets the shell for its actor, which
then calls ``POST /v1/functions/call`` on this server with that cookie. A
signed-out visitor gets the sign-in page from the browser sign-in door.
Assets and the served-build identity are public: they are the shipped
product, and browser QA reads the served build before signing in.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import Response
from fastapi.routing import APIRouter

from yoke_contracts.runtime_identity import PORTABILITY_SELFHOST, SERVED_BUILD_PATH
from yoke_core.api.routes.web_sign_in import signed_out_page
from yoke_core.api.web_session_auth import (
    WEB_SESSION_FUNCTION_CALL_PATH,
    web_session_context,
)
from yoke_core.ui.dashboard_routes import is_dashboard_path
from yoke_core.ui.served_source_identity import served_build_identity, served_install
from yoke_core.ui.workbench_shell import (
    asset_response,
    host_packet,
    served_build_response,
    shell_response,
)

router = APIRouter()

_ASSET_PREFIX = "/assets/"
_API_PREFIX = "/v1/"

#: The self-hosted host's capabilities. A browser is not a machine, so this
#: host asserts no onboarding machine fact; the engine answers it.
_SELF_HOST_CAPABILITIES = {
    "data": {"portability": {"mode": "self-host", "sectionOwned": False}},
}


def is_workbench_public_path(path: str) -> bool:
    """True for the workbench paths every visitor may read."""
    return path == SERVED_BUILD_PATH or path.startswith(_ASSET_PREFIX)


def is_workbench_page(method: str, path: str) -> bool:
    """True for a GET this router answers as a page.

    Every site-root GET outside ``/v1`` is the workbench's: the shell, one
    of its deep paths, or the workbench's own 404 for any other path.
    """
    return (
        method.upper() == "GET"
        and path != _API_PREFIX.rstrip("/")
        and not path.startswith(_API_PREFIX)
    )


def server_served_build() -> str:
    """The commit this server serves.

    A server image bakes its commit into ``YOKE_BUILD_SHA``; a server run
    from a source checkout names the checkout's commit instead.
    """
    return os.environ.get("YOKE_BUILD_SHA", "").strip() or served_build_identity()


def self_host_packet(actor_id: int) -> dict[str, Any]:
    """The mount packet for a signed-in browser on this server."""
    return host_packet(
        portability_mode=PORTABILITY_SELFHOST,
        install=served_install(),
        build=server_served_build(),
        environment_label=None,
        current_actor_id=actor_id,
        capabilities=_SELF_HOST_CAPABILITIES,
        function_call_endpoint=WEB_SESSION_FUNCTION_CALL_PATH,
    )


@router.get(_ASSET_PREFIX + "{asset_name}")
def asset(asset_name: str) -> Response:
    return asset_response(asset_name)


@router.get(SERVED_BUILD_PATH)
def served_build() -> Response:
    return served_build_response(server_served_build())


@router.get("/")
def workbench_page(request: Request) -> Response:
    """The shell for a signed-in browser; the sign-in page otherwise."""
    if not is_dashboard_path(request.url.path):
        raise HTTPException(status_code=404, detail="unknown dashboard route")
    ctx = web_session_context(request)
    if ctx is None:
        return signed_out_page()
    return shell_response(self_host_packet(ctx.actor_id))


router.get("/{path:path}")(workbench_page)


__all__ = [
    "is_workbench_page",
    "is_workbench_public_path",
    "router",
    "self_host_packet",
    "server_served_build",
]
