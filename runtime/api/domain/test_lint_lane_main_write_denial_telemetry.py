"""Coverage for lint_lane_main_write's cross-guard HarnessToolCallDenied emission.

This guard's own ``LaneMainWriteDenied`` event carries its rich lane
context, but close-out audits read the shared ``HarnessToolCallDenied``
name — so a denial here must land there too. See
:mod:`runtime.api.domain.test_lint_lane_main_write` for the guard's
allow/deny behavior coverage.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write


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


def test_denial_also_emits_harness_tool_call_denied(conn, repo):
    _seed_lane(conn, repo)
    target = repo / "runtime/api/foo.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    with mock.patch("yoke_core.hooks.denial.emit_denial_event") as canonical:
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Write",
            "tool_use_id": "tu-1",
            "tool_input": {"file_path": str(target)},
        })
    assert verdict.allow is False
    canonical.assert_called_once()
    kwargs = canonical.call_args.kwargs
    assert kwargs["check_id"] == "lint-lane-main-write"
    assert kwargs["guard_key"] == "lint_lane_main_write"
    assert kwargs["mode"] == "deny"
    assert kwargs["session_id"] == "sid-lane"
    assert kwargs["tool_use_id"] == "tu-1"
    assert str(target) in kwargs["reason"]
