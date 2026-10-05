"""Serving the universe workbench shell, shared by every host that serves it.

Two hosts serve the shell directly: the Local view
(:mod:`yoke_core.ui.server`, behind ``yoke ui up``) and the Yoke server
itself (:mod:`yoke_core.api.routes.workbench`, on a self-hosted server).
They answer the same three things — the app shell with the host's mount
packet injected, the asset roster, and the served-build identity — and
differ only in their door and in what their packet says. Each host owns
its door and its packet; this module owns the bytes.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response

from yoke_contracts.runtime_identity import build_runtime_identity, mount_fields
from yoke_core.ui.asset_roster import ASSET_CACHE_CONTROL, ASSET_CONTENT_TYPES

#: Marker pair in ``static/index.html`` the host replaces with its packet.
HOST_IDENTITY_MARKER = "/*YOKE_HOST_IDENTITY*/"


def asset_bytes(asset_name: str) -> bytes:
    """Read one shipped workbench asset."""
    from importlib.resources import files

    return files(__package__).joinpath("static", asset_name).read_bytes()


def host_packet(
    *,
    portability_mode: str,
    install: Mapping[str, Any],
    build: str,
    environment_label: Optional[str],
    current_actor_id: Optional[int],
    capabilities: Mapping[str, Any],
    function_call_endpoint: Optional[str] = None,
) -> dict[str, Any]:
    """The mount options a host injects into the shell.

    Identity comes from the canonical runtime-identity packet, so the
    footer reads the same fields on every host. ``function_call_endpoint``
    is omitted when the host answers the shell's default endpoint.
    """
    packet = mount_fields(
        build_runtime_identity(
            portability_mode=portability_mode,
            install=install,
            build=build,
            environment_label=environment_label,
        )
    )
    if current_actor_id is not None:
        packet["currentActor"] = {"id": str(current_actor_id), "kind": "human"}
    packet["capabilities"] = dict(capabilities)
    if function_call_endpoint:
        packet["functionCallEndpoint"] = function_call_endpoint
    return packet


def inject_host_packet(html: str, packet: Mapping[str, Any]) -> str:
    """Replace the shell's host-identity marker pair with ``packet``."""
    start = html.find(HOST_IDENTITY_MARKER)
    if start < 0:
        return html
    content_start = start + len(HOST_IDENTITY_MARKER)
    end = html.find(HOST_IDENTITY_MARKER, content_start)
    if end < 0:
        return html
    body = json.dumps(dict(packet), separators=(",", ":"))
    return html[:content_start] + body + html[end:]


def shell_response(packet: Mapping[str, Any]) -> HTMLResponse:
    """The app shell with ``packet`` injected."""
    shell = inject_host_packet(asset_bytes("index.html").decode("utf-8"), packet)
    return HTMLResponse(shell, headers={"Cache-Control": ASSET_CACHE_CONTROL})


def asset_response(asset_name: str) -> Response:
    """One roster asset, or 404 for a name outside the roster."""
    content_type = ASSET_CONTENT_TYPES.get(asset_name)
    if content_type is None:
        raise HTTPException(status_code=404, detail="unknown asset")
    return Response(
        asset_bytes(asset_name),
        media_type=content_type,
        headers={"Cache-Control": ASSET_CACHE_CONTROL},
    )


def served_build_response(build: str) -> Response:
    """The served commit as bare text.

    Plain text and nothing else: the reader matches a bare commit id, so a
    wrapper object would be indistinguishable from an unanswered question.
    An empty body is the honest answer when the host cannot name its
    commit, and fails that match rather than passing.
    """
    return Response(
        build,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


__all__ = [
    "HOST_IDENTITY_MARKER",
    "asset_bytes",
    "asset_response",
    "host_packet",
    "inject_host_packet",
    "served_build_response",
    "shell_response",
]
