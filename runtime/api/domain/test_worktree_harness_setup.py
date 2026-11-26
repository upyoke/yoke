"""Lane preparation propagates exact-path folder trust failures."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import worktree_create_provisioning as provisioning
from yoke_core.domain import worktree_provision
from yoke_core.domain.worktree_create_plan import (
    WorktreeCreationEntry,
    WorktreeCreationPlan,
)
from yoke_harness.harness_setup_reconcile import (
    FAILURES,
    RECOVERY,
    HarnessSetupResult,
    HarnessSetupRow,
)


@pytest.mark.parametrize("failure", ["refused", "failed"])
def test_exact_lane_trust_failure_preserves_lane_for_retry(
    monkeypatch, tmp_path, failure
):
    lane = tmp_path / "lane"
    entry = WorktreeCreationEntry(path=str(lane), branch="item-lane", lane_id=7)
    events = []
    persisted = []

    def reconcile(paths):
        assert paths == [lane.resolve()]
        assert persisted[-1] == (entry.lane_id, entry.branch, entry.path, entry.lane_role)
        events.append("reconciled")
        return HarnessSetupResult(
            (
                HarnessSetupRow(
                    str(lane.resolve()), "claude-code", "folder_trust", outcome,
                    detail="[WinError 5] Access is denied" if outcome == failure else "",
                    recovery=RECOVERY if outcome == failure else "",
                ),
                HarnessSetupRow(str(tmp_path), "claude-code", "folder_trust", "failed"),
                HarnessSetupRow(str(lane.resolve()), "codex", "hook_trust", "refused"),
                HarnessSetupRow(str(tmp_path), "claude-code", "posture", "refused"),
            )
        )

    monkeypatch.setattr(
        worktree_provision, "get_harness_setup_reconcile",
        lambda: SimpleNamespace(FAILURES=FAILURES, reconcile_harness_setup=reconcile),
    )
    monkeypatch.setattr(
        provisioning, "create_worktree_lane", lambda *_: events.append("created")
    )
    monkeypatch.setattr(
        provisioning, "persist_item_worktrees",
        lambda _item, lanes, _db: persisted.extend(lanes),
    )
    monkeypatch.setattr(provisioning, "install_lane_dependencies", lambda *_: None)
    monkeypatch.setattr(provisioning, "refresh_source_installed_views", lambda *_: None)
    monkeypatch.setattr(
        provisioning, "provision_worktree_harness_enablement", lambda *_: None
    )
    monkeypatch.setattr(
        provisioning, "provision_worktree_test_environment",
        lambda *_args, **_kwargs: events.append("readiness checked"),
    )

    def prepare(entry):
        return provisioning.provision_planned_lanes(
            WorktreeCreationPlan(worktrees=[entry], primary=entry),
            item_id=1, repo_root=str(tmp_path), base_branch="main",
            project="test-project", scripts_dir="", db_path=None,
        )

    outcome = failure
    refused = prepare(entry)
    assert refused.path == str(lane)
    assert refused.failed_branch == entry.branch
    assert refused.created
    assert f"claude-code: folder_trust {failure} {lane.resolve()}" in refused.error
    assert "[WinError 5] Access is denied" in refused.error
    assert RECOVERY in refused.error
    assert "rerun the same lane preparation command" in refused.error
    assert "hook_trust" not in refused.error
    assert events == ["created", "reconciled"]

    outcome = "written"
    reused = WorktreeCreationEntry(
        path=entry.path, branch=entry.branch, lane_id=entry.lane_id, preexisting=True,
    )
    ready = prepare(reused)
    assert not ready.error
    assert not ready.created
    assert ready.path == refused.path
    assert persisted[0] == persisted[1]
    assert events == ["created", "reconciled", "reconciled", "readiness checked"]
