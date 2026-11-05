# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json

from typing import Dict

from yoke_core.domain.observe_normalization import (
    TOOL_KIND_APPLY_PATCH,
    TOOL_KIND_BASH,
    TOOL_KIND_EDIT,
    TOOL_KIND_WRITE,
    ToolEventRecord,
)

from yoke_core.domain.path_claim_pre_edit_guard import (
    decide_for_record,
    evaluate,
    evaluate_payload,
)

from yoke_core.hooks.types import HookContext, Outcome


def _record(
    *,
    tool_kind=TOOL_KIND_EDIT,
    changed_paths=("runtime/api/domain/foo.py",),
    cwd="/tmp/yoke-worktrees/YOK-1577",
    session_id="sess-A",
    command="",
) -> ToolEventRecord:
    return ToolEventRecord(
        tool_kind=tool_kind,
        changed_paths=list(changed_paths),
        command=command,
        patch_body="",
        tool_name="Edit",
        session_id=session_id,
        cwd=cwd,
        project_dir=cwd,
    )
