"""Coverage for the local-subset DENY branch's denial-audit handoff.

``local_policies.py``'s client-only guard reimplementations (used by
``evaluate_local_subset`` for the HTTPS relay's client-side subset and for
fully local, no-transport evaluation) never call ``emit_denial_event``
themselves — a refusal rendered straight from this client subset used to
leave no durable audit row. ``evaluate_local_subset`` cannot record the
event itself (the client/server package boundary forbids any
``yoke_core``/DB-driver import here — see
``tests/import_graph/test_skeletons_importable.py``), so its DENY branch
now hands the audit fields back on ``LocalSubsetEvaluation.denial_audit``
for the caller that owns a live connection (``relay.py``) to relay.
"""

from __future__ import annotations

from runtime.harness.hook_local_subset_denial_telemetry_test_support import (
    _git as _git,
    dirty_repo as dirty_repo,
)


import json

from runtime.harness.hook_project_scope_test_support import project_map as project_map

from yoke_harness.hooks import local_subset
from yoke_harness.hooks.deadline import start_hook_deadline


def test_destructive_git_deny_carries_denial_audit(dirty_repo):
    payload = {
        "session_id": "sid-local",
        "tool_name": "Bash",
        "tool_use_id": "tu-local-1",
        "cwd": str(dirty_repo),
        "tool_input": {"command": "git reset --hard"},
    }
    stdin_data = json.dumps(payload)
    deadline = start_hook_deadline()
    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        stdin_data,
        "claude",
        None,
        deadline,
        lint_config_snapshot={},
    )
    assert result.denied is True
    assert "BLOCKED" in result.stdout
    audit = result.denial_audit
    assert audit is not None
    assert audit["guard_key"] == "yoke_core.domain.lint_destructive_git"
    assert audit["hook"] == "yoke_core.domain.lint_destructive_git"
    assert audit["mode"] == "deny"
    assert audit["session_id"] == "sid-local"
    assert audit["tool_use_id"] == "tu-local-1"
    assert audit["command_snippet"] == "git reset --hard"


def test_warn_mode_denial_audit_is_absent(dirty_repo):
    """A downgraded (warn-mode) guard never renders a deny — no audit."""
    payload = {
        "session_id": "sid-local",
        "tool_name": "Bash",
        "cwd": str(dirty_repo),
        "tool_input": {"command": "git reset --hard"},
    }
    stdin_data = json.dumps(payload)
    deadline = start_hook_deadline()
    snapshot = {"lint_destructive_git": {"mode": "warn", "allow_warn": True}}
    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        stdin_data,
        "claude",
        None,
        deadline,
        lint_config_snapshot=snapshot,
    )
    assert result.denied is False
    assert result.denial_audit is None
