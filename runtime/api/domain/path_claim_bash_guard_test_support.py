# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Dict

from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for

from yoke_core.domain.path_claim_bash_guard import (
    decide_for_record,
    evaluate_payload,
)


def _claim_dict(
    *,
    claim_id: int = 99,
    integration_target: str = "main",
    state: str = "active",
    covered_paths: tuple = ("runtime/api/domain",),
    worktree_path: str = "/tmp/yoke-worktrees/YOK-1577",
    public_ref: str | None = "YOK-1577",
) -> Dict:
    claim = {
        "id": claim_id,
        "owner_kind": "item",
        "owner_item_id": 1577,
        "integration_target": integration_target,
        "state": state,
        "covered_paths": covered_paths,
        "worktree_path": worktree_path,
    }
    if public_ref is not None:
        claim["public_ref"] = public_ref
    return claim


def _payload(*, command: str, cwd: str, session_id: str = "sess-A") -> Dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
        "session_id": session_id,
    }
