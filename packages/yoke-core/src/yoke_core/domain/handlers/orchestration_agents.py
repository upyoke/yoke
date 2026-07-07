"""Agents-render orchestration handlers.

Function ids registered here:

- ``agents.render.run.run`` — invokes :func:`yoke_core.domain.agents_render.write_all_and_record`
  against an operator-selected target_root (defaulting to the canonical
  repo root). Returns the per-output action map: ``write`` / ``skip`` /
  ``would-write``. Post-render render-relationship registration is
  shared with the CLI surface.
- ``agents.render.check.run`` — invokes
  :func:`yoke_core.domain.agents_render.detect_substrate_drift` and
  returns the structured drift list.

Both route through the existing renderer without forking. Both carry
``claim_required_kind=None`` (renders are project-wide, not item-scoped).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


# ---------------------------------------------------------------------------
# agents.render.run.run
# ---------------------------------------------------------------------------


class AgentsRenderRunRequest(BaseModel):
    target_root: Optional[str] = None
    dry_run: bool = False


class AgentsRenderRunResponse(BaseModel):
    target_root: str
    dry_run: bool
    results: Dict[str, str]


def _resolve_target_root(payload_root: Optional[str]) -> Path:
    if payload_root:
        return Path(str(payload_root))
    from yoke_core.domain.rebuild_board import resolve_main_repo_root

    return Path(resolve_main_repo_root(None))


def handle_agents_render_run(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.agents_render import write_all_and_record

    payload = request.payload or {}
    payload_root = payload.get("target_root")
    dry_run = bool(payload.get("dry_run", False))
    try:
        target_root = _resolve_target_root(payload_root)
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=f"target_root cannot be resolved: {exc}",
                jsonpath="$.payload.target_root",
            ),
        )
    try:
        rendered = write_all_and_record(target_root=target_root, dry_run=dry_run)
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="downstream_failure",
                message=f"agents_render.write_all failed: {exc}",
            ),
        )
    # Project just the action so the response is compact; full content is
    # available via packets.render or agents.render.check.
    results = {rel: action for rel, (action, _content) in rendered.items()}
    return HandlerOutcome(
        result_payload={
            "target_root": str(target_root),
            "dry_run": dry_run,
            "results": results,
        },
        primary_success=True,
    )


# ---------------------------------------------------------------------------
# agents.render.check.run
# ---------------------------------------------------------------------------


class AgentsRenderCheckRequest(BaseModel):
    target_root: Optional[str] = None


class AgentsRenderCheckResponse(BaseModel):
    target_root: str
    drift: List[str]


def handle_agents_render_check(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.agents_render import detect_substrate_drift

    payload = request.payload or {}
    payload_root = payload.get("target_root")
    try:
        target_root = _resolve_target_root(payload_root)
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=f"target_root cannot be resolved: {exc}",
                jsonpath="$.payload.target_root",
            ),
        )
    drift = list(detect_substrate_drift(target_root=target_root))
    return HandlerOutcome(
        result_payload={
            "target_root": str(target_root),
            "drift": drift,
        },
        primary_success=True,
    )


__all__ = [
    "AgentsRenderRunRequest", "AgentsRenderRunResponse",
    "handle_agents_render_run",
    "AgentsRenderCheckRequest", "AgentsRenderCheckResponse",
    "handle_agents_render_check",
]
