"""Orchestration handlers: ``board.*`` plus the packets.* readers.

Function ids registered here:

- ``board.data.get`` — runs the board's full DB query plan server-side
  (:func:`yoke_core.board.data.collect_board_data`) and returns the
  recorded data payload; rendering and all file I/O stay client-side,
  so the same call works over https against a server with no checkout.
- ``board.rebuild.run`` — invokes :func:`yoke_core.domain.rebuild_board.rebuild`
  and returns the new board file's hash + line count. Carries
  ``claim_required_kind=None`` because the rebuild is a project-wide
  refresh, not a per-item mutation.
- ``packets.render.run`` / ``packets.check.run`` — typed wrappers over
  :func:`yoke_core.domain.schema_api_context.render_role_packet` and
  :func:`detect_seed_drift`. No claim required.

Sibling module ``orchestration_agents`` hosts ``agents.render.run`` /
``agents.render.check`` so each file stays under the 350-line budget.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


# ---------------------------------------------------------------------------
# board.data.get
# ---------------------------------------------------------------------------


class BoardDataGetRequest(BaseModel):
    scope: str = "all"
    config_values: Dict[str, Any] = Field(default_factory=dict)
    zen_vision_count: int = 0
    repo_root_token: Optional[str] = None


class BoardDataGetResponse(BaseModel):
    version: int
    scope: str
    entry_count: int
    entries: List[Dict[str, Any]]


def handle_board_data_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Collect the board's recorded query plan for a client-side render.

    The payload carries the CLIENT's query-shaping inputs: scope, the
    parsed board.json values, the zen vision-entry count (the rendered
    VISION doc is a client-local file whose section count feeds a
    timeline SQL parameter), and the client's repo-root token (presence
    gates the velocity meter's repo resolution query). Art, seed, and
    label text shape only markdown, which collection discards.
    """
    from yoke_contracts.board.config import BoardConfig
    from yoke_core.board.data import BoardDataError, collect_board_data
    from yoke_core.board.db import BoardDB

    try:
        payload = BoardDataGetRequest.model_validate(request.payload or {})
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid", message=f"payload invalid: {exc}",
                jsonpath="$.payload",
            ),
        )
    try:
        config = BoardConfig(**dict(payload.config_values))
    except TypeError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=(
                    "config_values does not match this server's BoardConfig "
                    f"({exc}); client and server board contracts diverge"
                ),
                jsonpath="$.payload.config_values",
            ),
        )
    vision_entries = [("vision", "")] * max(0, int(payload.zen_vision_count))
    visible_project_ids = _visible_project_ids_from_options(request.options)
    try:
        with BoardDB() as db:
            data = collect_board_data(
                db,
                scope=payload.scope,
                config=config,
                repo_root=payload.repo_root_token,
                vision_entries=vision_entries,
                visible_project_ids=visible_project_ids,
            )
    except BoardDataError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(code="downstream_failure", message=str(exc)),
        )
    return HandlerOutcome(result_payload=data, primary_success=True)


def _visible_project_ids_from_options(options: Dict[str, Any] | None) -> List[int] | None:
    raw = (options or {}).get("visible_project_ids")
    if raw is None:
        return None
    if not isinstance(raw, list):
        return []
    ids: List[int] = []
    for value in raw:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(set(ids))


# ---------------------------------------------------------------------------
# board.rebuild.run
# ---------------------------------------------------------------------------


class BoardRebuildRequest(BaseModel):
    force: bool = False
    output_name: Optional[str] = None
    scope: Optional[str] = None
    repo_root: Optional[str] = None


class BoardRebuildResponse(BaseModel):
    board_path: str
    status: str
    changed: bool
    targets: List[Dict[str, Any]] = Field(default_factory=list)
    message: str = ""
    sha256: str
    line_count: int
    exit_code: int


def handle_board_rebuild(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain import rebuild_board_outcome as rb_outcome
    from yoke_core.domain.rebuild_board import (
        rebuild,
        resolve_board_path,
        try_resolve_main_repo_root,
    )

    payload = request.payload or {}
    force = bool(payload.get("force", False))
    output_name = payload.get("output_name")
    scope = payload.get("scope")
    repo_root_raw = payload.get("repo_root")
    repo_root_arg = str(repo_root_raw) if repo_root_raw else None
    repo_root = try_resolve_main_repo_root(repo_root_arg)
    if repo_root is None:
        # No local checkout (a server-side https board.rebuild has no repo /
        # local BOARD.md). The board is a client-local view the in-checkout
        # client rebuilds — a server-side rebuild is a successful no-op.
        return HandlerOutcome(
            primary_success=True,
            result_payload={
                "board_path": "", "status": "skipped-no-checkout",
                "changed": False,
                "message": "no local checkout; board is a client-local view",
                "targets": [], "sha256": "", "line_count": 0, "exit_code": 0,
            },
        )
    result = rebuild(
        repo_arg=str(repo_root),
        force=force,
        output_name=output_name,
        scope=scope,
        emit=False,
    )
    if isinstance(result, int):
        result = rb_outcome.RebuildOutcome(
            rb_outcome.REBUILT if result == 0 else rb_outcome.FAILED,
            int(result),
        )
    board_path = Path(result.board_path) if result.board_path else (
        resolve_board_path(repo_root, output_name)
    )
    sha = ""
    line_count = 0
    if board_path.is_file():
        content = board_path.read_text(encoding="utf-8")
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        line_count = content.count("\n") + (
            0 if content.endswith("\n") or not content else 1
        )
    error_message = (
        f"rebuild_board exited with {result.exit_code} "
        f"status={result.status}"
    )
    if result.message:
        error_message = f"{error_message}: {result.message}"
    return HandlerOutcome(
        result_payload={
            "board_path": str(board_path),
            "status": result.status,
            "changed": result.changed,
            "message": result.message,
            "targets": [
                {
                    "board_path": child.board_path,
                    "status": child.status,
                    "changed": child.changed,
                    "exit_code": child.exit_code,
                    "message": child.message,
                }
                for child in result.children
            ],
            "sha256": sha,
            "line_count": line_count,
            "exit_code": int(result.exit_code),
        },
        primary_success=(result.exit_code == 0),
        error=(
            None if result.exit_code == 0 else FunctionError(
                code="downstream_failure",
                message=error_message,
            )
        ),
    )


# ---------------------------------------------------------------------------
# packets.render.run
# ---------------------------------------------------------------------------


class PacketsRenderRequest(BaseModel):
    role: str


class PacketsRenderResponse(BaseModel):
    role: str
    body: str
    byte_count: int


def handle_packets_render(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.schema_api_context import render_role_packet

    payload = request.payload or {}
    role = payload.get("role")
    if not isinstance(role, str) or not role:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid", message="role is required",
                jsonpath="$.payload.role",
            ),
        )
    try:
        body = render_role_packet(role)
    except KeyError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="not_found",
                message=f"unknown packet role {role!r}: {exc}",
                jsonpath="$.payload.role",
            ),
        )
    return HandlerOutcome(
        result_payload={
            "role": role,
            "body": body,
            "byte_count": len(body.encode("utf-8")),
        },
        primary_success=True,
    )


# ---------------------------------------------------------------------------
# packets.check.run
# ---------------------------------------------------------------------------


class PacketsCheckRequest(BaseModel):
    pass


class PacketsCheckResponse(BaseModel):
    drift: List[str]
    seed_ok: bool


def handle_packets_check(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.schema_api_context import detect_seed_drift

    drift = list(detect_seed_drift())
    return HandlerOutcome(
        result_payload={"drift": drift, "seed_ok": not drift},
        primary_success=True,
    )


__all__ = [
    "BoardDataGetRequest", "BoardDataGetResponse", "handle_board_data_get",
    "BoardRebuildRequest", "BoardRebuildResponse", "handle_board_rebuild",
    "PacketsRenderRequest", "PacketsRenderResponse", "handle_packets_render",
    "PacketsCheckRequest", "PacketsCheckResponse", "handle_packets_check",
]
