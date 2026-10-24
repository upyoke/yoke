"""Coverage for the audit fields lint_lane_main_write hands the hook runner.

This guard's own ``LaneMainWriteDenied`` event carries its rich lane
context. The shared ``HarnessToolCallDenied`` row is recorded by the hook
runner from the returned decision, so the decision must carry the reason
and audit outcome. See :mod:`runtime.api.domain.test_lint_lane_main_write`
for the guard's allow/deny behavior coverage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write
from yoke_core.hooks import mode_gate
from yoke_core.hooks.guard_denial_record import guard_audit_outcome
from yoke_core.hooks.types import HookContext, Next, Outcome


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _seed_lane(conn, repo, *, session_id="sid-lane", item_id=2013):
    register_machine_checkout(
        Path(repo).parent / "machine-config", Path(repo), project_id=1,
    )
    seed_item(
        conn, item_id=item_id, branch=f"YOK-{item_id}", status="implementing",
        repo_path=repo,
    )
    seed_item_claim(conn, session_id, item_id=item_id)
    wt = repo / ".worktrees" / f"YOK-{item_id}"
    wt.mkdir(parents=True, exist_ok=True)
    return wt


MODULE_ID = "yoke_core.domain.lint_lane_main_write"


def _main_write_decision(repo):
    target = repo / "runtime/api/foo.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": "sid-lane",
        "tool_name": "Write",
        "tool_use_id": "tu-1",
        "tool_input": {"file_path": str(target)},
    }
    record = HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name="Write",
        session_id="sid-lane",
        target_root=str(repo),
    )
    return target, record, lint_lane_main_write.evaluate(record)


def test_denial_decision_carries_reason_for_the_runner_audit_row(conn, repo):
    _seed_lane(conn, repo)
    target, record, decision = _main_write_decision(repo)
    assert decision.outcome is Outcome.DENY
    assert decision.block is True
    assert decision.next is Next.STOP
    assert "mode" not in decision.audit_fields
    assert str(target) in decision.audit_fields["reason"]
    assert "lint_lane_main_write=deny" in decision.message
    assert guard_audit_outcome(decision) == "denied"
    gated = mode_gate.apply_mode(decision, MODULE_ID, context=record)
    assert gated.audit_fields["policy_mode"] == "deny"
