"""Pre-edit / pre-write / pre-apply_patch guard coverage."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

import pytest

from yoke_core.domain.observe_normalization import (
    TOOL_KIND_APPLY_PATCH,
    TOOL_KIND_BASH,
    TOOL_KIND_EDIT,
    TOOL_KIND_WRITE,
    ToolEventRecord,
)
from yoke_core.domain.path_claim_pre_edit_guard import (
    Verdict,
    decide_for_record,
    evaluate,
    evaluate_payload,
)
from yoke_core.domain._path_claim_guard_test_helpers import live_db
from runtime.harness.hook_runner.types import HookContext, Outcome


def _claim_dict(*, claim_id=99, item_id=1577, integration_target="main",
                state="active", covered_paths=("runtime/api/domain",),
                worktree_path="/tmp/yoke-worktrees/YOK-1577",
                project_repo_path="") -> Dict:
    return {"id": claim_id, "item_id": item_id,
            "integration_target": integration_target, "state": state,
            "covered_paths": covered_paths, "worktree_path": worktree_path,
            "project_repo_path": project_repo_path}


def _record(*, tool_kind=TOOL_KIND_EDIT,
            changed_paths=("runtime/api/domain/foo.py",),
            cwd="/tmp/yoke-worktrees/YOK-1577", session_id="sess-A",
            command="") -> ToolEventRecord:
    return ToolEventRecord(tool_kind=tool_kind, changed_paths=list(changed_paths),
                           command=command, patch_body="", tool_name="Edit",
                           session_id=session_id, cwd=cwd, project_dir=cwd)


class TestInClaim:
    def test_allow_when_target_in_coverage(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        record = _record(
            changed_paths=(str(worktree / "runtime/api/domain/foo.py"),),
            cwd=str(worktree),
        )
        verdict = evaluate_payload(record, claim=claim)
        assert verdict.outcome == "allow"

    def test_allow_absolute_tmp_target_outside_repo(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        record = _record(
            tool_kind=TOOL_KIND_WRITE,
            changed_paths=("/tmp/yoke-stdin-pipe.abc123",),
            cwd=str(worktree),
        )
        verdict = evaluate_payload(record, claim=claim)
        assert verdict.outcome == "allow"

    def test_allow_when_relative_target_in_coverage(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        record = _record(
            changed_paths=("runtime/api/domain/foo.py",),
            cwd=str(worktree),
        )
        verdict = evaluate_payload(record, claim=claim)
        assert verdict.outcome == "allow"


class TestOutOfClaim:
    def test_deny_with_widen_template(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        record = _record(
            changed_paths=("docs/never-covered.md",),
            cwd=str(worktree),
        )
        verdict = evaluate_payload(record, claim=claim)
        assert verdict.outcome == "deny"
        assert verdict.failure_mode == "out-of-claim"
        assert (
            "yoke claims path widen --claim-id 99 "
            "--add-paths docs/never-covered.md "
            "--reason \"cover target path\" --item YOK-1577"
        ) in verdict.narrative

    def test_deny_records_target_path(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        record = _record(
            changed_paths=("docs/oof.md",),
            cwd=str(worktree),
        )
        verdict = evaluate_payload(record, claim=claim)
        assert verdict.target_path == "docs/oof.md"
        assert verdict.claim_id == 99


class TestWorktreeUnresolved:
    """AC-22/AC-23: distinct failure.mode + narrative when claim is
    not worktree-bound. Narrative teaches ``worktree_preflight`` and
    intentionally omits claim-widen guidance."""

    def test_failure_mode_and_narrative(self, tmp_path):
        v = evaluate_payload(
            _record(changed_paths=("docs/x.md",), cwd=str(tmp_path)),
            claim=_claim_dict(worktree_path=None),
        )
        assert v.outcome == "deny" and v.failure_mode == "worktree-unresolved"
        n = v.narrative
        assert "items.worktree" in n and "worktree_preflight" in n
        assert "yoke_core.cli.db_router items update" in n
        assert "claims path widen" not in n


class TestWrongCwd:
    def test_deny_when_path_in_main_checkout(self, tmp_path):
        # Worktree is at tmp_path/YOK-XXXX, but the absolute target
        # path resolves to tmp_path/main/runtime/api/domain/foo.py
        # — the relative string IS in coverage but the physical path
        # lives outside the worktree.
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        main_repo = tmp_path / "main"
        (main_repo / "runtime/api/domain").mkdir(parents=True)
        target = main_repo / "runtime/api/domain/foo.py"
        target.write_text("# placeholder\n")
        claim = _claim_dict(worktree_path=str(worktree))
        record = _record(
            changed_paths=(str(target),),
            cwd=str(main_repo),  # cwd is main, but claim is in worktree
        )
        verdict = evaluate_payload(record, claim=claim)
        assert verdict.outcome == "deny"
        assert verdict.failure_mode == "wrong-cwd"
        assert "Wrong working tree" in verdict.narrative
        assert str(worktree) in verdict.narrative

    def test_main_repo_absolute_path_still_denies(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        main_repo = tmp_path / "main"
        (main_repo / "runtime/api/domain").mkdir(parents=True)
        target = main_repo / "runtime/api/domain/foo.py"
        target.write_text("# placeholder\n")
        claim = _claim_dict(
            worktree_path=str(worktree),
            project_repo_path=str(main_repo),
        )
        record = _record(
            changed_paths=(str(target),),
            cwd=str(worktree),
        )
        verdict = evaluate_payload(record, claim=claim)
        assert verdict.outcome == "deny"
        assert verdict.failure_mode == "wrong-cwd"


class TestNoOps:
    def test_bash_kind_skipped(self):
        record = _record(tool_kind=TOOL_KIND_BASH, changed_paths=())
        verdict = evaluate_payload(record, claim=_claim_dict())
        assert verdict.outcome == "allow"

    def test_no_changed_paths_allowed(self):
        record = _record(tool_kind=TOOL_KIND_EDIT, changed_paths=())
        verdict = evaluate_payload(record, claim=_claim_dict())
        assert verdict.outcome == "allow"

    def test_no_claim_allows_freely(self):
        record = _record(changed_paths=("docs/whatever.md",))
        verdict = evaluate_payload(record, claim=None)
        # No active claim — guard does not block.
        assert verdict.outcome == "allow"


class TestApplyPatchKind:
    def test_apply_patch_inspected_with_changed_paths(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        record = _record(
            tool_kind=TOOL_KIND_APPLY_PATCH,
            changed_paths=("docs/never-covered.md",),
            cwd=str(worktree),
        )
        verdict = evaluate_payload(record, claim=claim)
        assert verdict.outcome == "deny"
        assert verdict.failure_mode == "out-of-claim"


class TestWriteKind:
    def test_write_inspected(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        record = _record(
            tool_kind=TOOL_KIND_WRITE,
            changed_paths=("docs/never-covered.md",),
            cwd=str(worktree),
        )
        verdict = evaluate_payload(record, claim=claim)
        assert verdict.outcome == "deny"


class TestPipelineAdapter:
    def test_decide_for_record_returns_none_on_allow(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        record = _record(
            changed_paths=("runtime/api/domain/foo.py",),
            cwd=str(worktree),
        )
        # No claim resolved against the live DB — adapter returns None.
        assert decide_for_record(record) is None

    def test_decide_for_record_skips_bash(self):
        record = _record(tool_kind=TOOL_KIND_BASH, changed_paths=())
        assert decide_for_record(record) is None


class TestTypedEvaluateEntrypoint:
    def test_evaluate_returns_deny_envelope_on_out_of_claim(
        self, tmp_path, monkeypatch
    ):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        monkeypatch.setattr(
            "yoke_core.domain.path_claim_pre_edit_guard.resolve_active_claim_for_session",
            lambda session_id, conn=None: _claim_dict(worktree_path=str(worktree)),
        )
        monkeypatch.setattr(
            "yoke_core.domain.path_claim_pre_edit_guard._emit_denial",
            lambda **_kwargs: None,
        )
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "docs/oof.md"},
            "cwd": str(worktree),
            "session_id": "sess-A",
        }
        record = HookContext(
            event_name="PreToolUse", executor_family="claude",
            executor_surface="claude", payload=payload,
            tool_name="Write", cwd=str(worktree), session_id="sess-A",
        )
        decision = evaluate(record)
        assert decision.outcome is Outcome.DENY
        assert decision.block is True
        hook = json.loads(decision.message)["hookSpecificOutput"]
        assert hook["hookEventName"] == "PreToolUse"
        assert hook["permissionDecision"] == "deny"
        assert (
            "yoke claims path widen --claim-id 99 "
            "--add-paths docs/oof.md --reason \"cover target path\" "
            "--item YOK-1577"
        ) in hook["permissionDecisionReason"]

    def test_evaluate_returns_noop_when_no_record(self):
        # Tool name that doesn't build a record => NOOP.
        record = HookContext(
            event_name="PreToolUse", executor_family="claude",
            executor_surface="claude",
            payload={"tool_name": "Bash", "tool_input": {}},
            tool_name="Bash",
        )
        decision = evaluate(record)
        assert decision.outcome is Outcome.NOOP


class TestLiveNoConnEpicResolution:
    """AC-9/13/14/15: live no-conn epic evaluation."""

    def test_lanes_allow_and_deny_carries_effective_wt(self, tmp_path, live_db):
        # AC-9/13/15: same session, two targets in two chains both allow.
        # A deny inside a chain surfaces the lane path (not None).
        repo = tmp_path / "repo"
        for sub in ("lane-a/runtime/api/domain", "lane-b/runtime/api/domain",
                    "lane-a/docs"):
            (repo / ".worktrees" / sub).mkdir(parents=True)
        live_db(repo_path=repo, item_id=900, item_type="epic",
                chains=("lane-a", "lane-b"),
                covered_paths=("runtime/api/domain",), session_id="engineer-1")
        def _rec(target, cwd):
            return ToolEventRecord(
                tool_kind=TOOL_KIND_EDIT, changed_paths=[target],
                tool_name="Edit", session_id="engineer-1", cwd=cwd,
            )
        a = str(repo / ".worktrees/lane-a/runtime/api/domain/a.py")
        b = str(repo / ".worktrees/lane-b/runtime/api/domain/b.py")
        assert evaluate_payload(_rec(a, str(repo / ".worktrees/lane-a"))).outcome == "allow"
        assert evaluate_payload(_rec(b, str(repo / ".worktrees/lane-b"))).outcome == "allow"
        deny_t = str(repo / ".worktrees/lane-a/docs/never-covered.md")
        v = evaluate_payload(_rec(deny_t, str(repo / ".worktrees/lane-a")))
        assert v.outcome == "deny" and v.failure_mode == "out-of-claim"
        ewt = v.extra.get("expected_worktree_path")
        assert ewt is not None and "lane-a" in ewt
