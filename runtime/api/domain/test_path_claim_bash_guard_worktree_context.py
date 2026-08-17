"""Bash path-claim guard coverage for worktree-aware evaluation."""

from __future__ import annotations

import json
import os
from pathlib import Path

from yoke_core.domain import path_claim_bash_guard as bash_guard
from yoke_core.domain.path_claim_bash_guard import evaluate, evaluate_payload
from runtime.api.domain.test_path_claim_bash_guard import _claim_dict, _payload
from yoke_core.hooks.types import HookContext, Outcome


class TestCurrentItemWorktreeNarrative:
    def test_oof_under_bound_worktree_pivots_to_preflight(self, tmp_path):
        worktree = Path(os.sep).joinpath(
            "var",
            "tmp",
            f"yoke-claim-{tmp_path.name}",
            "YOK-1577",
        )
        target = worktree.joinpath("docs", "oof.md")
        claim = _claim_dict(worktree_path=str(worktree))
        payload = _payload(command=f"rm {target}", cwd=str(worktree))
        verdict = evaluate_payload(payload, claim=claim)
        assert verdict.outcome == "deny"
        assert verdict.failure_mode == "out-of-claim"
        assert (
            "python3 -m yoke_core.domain.worktree_preflight --item YOK-1577"
            in verdict.narrative
        )
        assert "current-item worktree" in verdict.narrative
        assert "yoke claims path widen --claim-id 99" in verdict.narrative
        assert "--add-paths" in verdict.narrative
        assert "--item YOK-1577" in verdict.narrative

    def test_oof_outside_worktree_keeps_widen_headline(self, tmp_path):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        outside = tmp_path / "main"
        outside.mkdir()
        claim = _claim_dict(worktree_path=str(worktree))
        payload = _payload(command="rm docs/oof.md", cwd=str(outside))
        verdict = evaluate_payload(payload, claim=claim)
        assert verdict.outcome == "deny"
        assert (
            "Path is outside this session's active claim coverage." in verdict.narrative
        )
        assert "worktree_preflight" not in verdict.narrative

    def test_claim_with_no_worktree_emits_worktree_unresolved(self, tmp_path):
        (tmp_path / "main").mkdir()
        verdict = evaluate_payload(
            _payload(command="rm docs/oof.md", cwd=str(tmp_path / "main")),
            claim=_claim_dict(worktree_path=""),
        )
        assert verdict.outcome == "deny" and "worktree_preflight" in verdict.narrative
        assert "item_worktrees row" in verdict.narrative
        assert "widen" not in verdict.narrative


class TestLiveNoConnEpicResolution:
    def test_bash_lanes_allow_and_deny_carries_effective_wt(self, tmp_path, live_db):
        repo = tmp_path / "repo"
        for sub in (
            "lane-a/runtime/api/domain",
            "lane-b/runtime/api/domain",
            "lane-a/docs",
        ):
            (repo / ".worktrees" / sub).mkdir(parents=True)
        live_db(
            repo_path=repo,
            item_id=900,
            workflow_id="epic",
            chains=("lane-a", "lane-b"),
            covered_paths=("runtime/api/domain",),
            session_id="engineer-1",
        )
        a = repo / ".worktrees/lane-a/runtime/api/domain/a.py"
        b = repo / ".worktrees/lane-b/runtime/api/domain/b.py"
        assert (
            evaluate_payload(
                _payload(
                    command="rm runtime/api/domain/a.py",
                    cwd=str(a.parents[3]),
                    session_id="engineer-1",
                )
            ).outcome
            == "allow"
        )
        assert (
            evaluate_payload(
                _payload(
                    command="rm runtime/api/domain/b.py",
                    cwd=str(b.parents[3]),
                    session_id="engineer-1",
                )
            ).outcome
            == "allow"
        )
        deny_target = repo / ".worktrees/lane-a/docs/never-covered.md"
        verdict = evaluate_payload(
            _payload(
                command="rm docs/never-covered.md",
                cwd=str(deny_target.parents[1]),
                session_id="engineer-1",
            )
        )
        assert verdict.outcome == "deny"
        assert "lane-a" in verdict.extra["expected_worktree_path"]


class TestTypedEvaluateEntrypoint:
    def _record(self, payload, cwd):
        return HookContext(
            event_name="PreToolUse",
            executor_family="claude",
            executor_surface="claude",
            payload=payload,
            tool_name="Bash",
            cwd=cwd,
            session_id="sess-A",
        )

    def test_evaluate_returns_deny_envelope_on_out_of_claim(
        self, tmp_path, monkeypatch
    ):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        monkeypatch.setattr(
            bash_guard,
            "resolve_active_claim_for_session",
            lambda session_id, conn=None, **_kwargs: _claim_dict(
                worktree_path=str(worktree)
            ),
        )
        monkeypatch.setattr(bash_guard, "_emit_denial", lambda **_kwargs: None)
        decision = evaluate(
            self._record(
                _payload(command="rm docs/oof.md", cwd=str(worktree)), str(worktree)
            )
        )
        assert decision.outcome is Outcome.DENY and decision.block is True
        hook = json.loads(decision.message)["hookSpecificOutput"]
        assert hook["hookEventName"] == "PreToolUse"
        assert hook["permissionDecision"] == "deny"
        assert (
            "yoke claims path widen --claim-id 99 "
            '--add-paths docs/oof.md --reason "cover target path" '
            "--item YOK-1577"
        ) in hook["permissionDecisionReason"]

    def test_evaluate_returns_noop_on_allow(self, tmp_path, monkeypatch):
        worktree = tmp_path / "YOK-1577"
        worktree.mkdir()
        monkeypatch.setattr(
            bash_guard,
            "resolve_active_claim_for_session",
            lambda session_id, conn=None, **_kwargs: None,
        )
        decision = evaluate(
            self._record(_payload(command="ls", cwd=str(worktree)), str(worktree))
        )
        assert decision.outcome is Outcome.NOOP
