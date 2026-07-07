"""Orchestrator tests for the harness-universal worktree preflight."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import worktree_preflight as wp
from yoke_core.domain import worktree_preflight_steps as steps


@pytest.fixture
def repo_layout(tmp_path):
    """Build a minimal git-initialized repo+worktree layout for orchestrator tests."""
    import subprocess

    repo = tmp_path / "main"
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "--quiet", str(repo)], check=True, capture_output=True,
    )
    worktrees = repo / ".worktrees"
    worktree = worktrees / "YOK-9001"
    worktrees.mkdir(parents=True)
    worktree.mkdir()
    return SimpleNamespace(
        root=str(repo), worktree=str(worktree), worktrees=str(worktrees),
    )


def _patch_steps(
    monkeypatch,
    *,
    claim_outcome=(True, "(already owned)"),
    activate_outcome=(True, "", [39]),
    dirty_outcome=(False, "", []),
    create_result=None,
):
    monkeypatch.setattr(wp, "claim_work", lambda item_id: claim_outcome)
    monkeypatch.setattr(wp, "activate_path_claims", lambda item_id: activate_outcome)
    monkeypatch.setattr(wp, "check_dirty_main", lambda repo_root: dirty_outcome)
    if create_result is not None:
        from yoke_core.domain import worktree_create

        def _fake_create(**kwargs):
            return create_result

        monkeypatch.setattr(worktree_create, "create_worktree", _fake_create)


class TestReEntryWithExistingWorktree:
    def test_static_cwd_envelope_describes_supported_substrate(
        self, repo_layout, monkeypatch
    ):
        from yoke_core.domain import worktree_create
        _patch_steps(
            monkeypatch,
            create_result=worktree_create.CreateWorktreeResult(
                path=repo_layout.worktree,
                branch="YOK-9001",
                created=False,
            ),
        )
        outcome = wp.run_preflight(
            item_id=9001,
            repo_root=repo_layout.root,
            session_id="sess",
            actual_cwd=repo_layout.root,
        )
        assert outcome.ok is True
        assert outcome.worktree_path == repo_layout.worktree
        assert outcome.semantic_scope == "worktree"
        assert outcome.physical_cwd_mode == steps.CWD_MODE_STATIC
        # When cwd is static, the envelope notes carry an advisory line
        # with the worktree path and the absolute / `git -C` shape.
        assert any(repo_layout.worktree in note for note in outcome.notes)
        assert "worktree:reused" in outcome.actions_taken

    def test_matched_cwd_omits_static_note(self, repo_layout, monkeypatch):
        from yoke_core.domain import worktree_create
        _patch_steps(
            monkeypatch,
            create_result=worktree_create.CreateWorktreeResult(
                path=repo_layout.worktree,
                branch="YOK-9001",
                created=False,
            ),
        )
        outcome = wp.run_preflight(
            item_id=9001,
            repo_root=repo_layout.root,
            session_id="sess",
            actual_cwd=repo_layout.worktree,
        )
        assert outcome.ok is True
        assert outcome.physical_cwd_mode == steps.CWD_MODE_MATCHED
        # The advisory note only fires on static cwd; matched cwd is silent.
        assert all("Use absolute paths" not in note for note in outcome.notes)


class TestBlocks:
    def test_work_claim_conflict_returns_block_kind_with_no_widen(
        self, repo_layout, monkeypatch
    ):
        _patch_steps(
            monkeypatch,
            claim_outcome=(False, "already claimed by session 'alt'"),
        )
        outcome = wp.run_preflight(
            item_id=9001,
            repo_root=repo_layout.root,
            session_id="sess",
            actual_cwd=repo_layout.root,
        )
        assert outcome.ok is False
        assert outcome.block_kind == steps.BLOCK_WORK_CLAIM
        # The narrative must NOT teach claim-widening — that is the wrong
        # remediation per the operator handoff addendum.
        assert "widen" in outcome.narrative.lower()  # appears in the disclaimer
        assert "NOT to widen a path claim" in outcome.narrative

    def test_path_claim_block_surfaces_stderr(self, repo_layout, monkeypatch):
        _patch_steps(
            monkeypatch,
            activate_outcome=(False, "BLOCKED: claim 39 is blocked", []),
        )
        outcome = wp.run_preflight(
            item_id=9001,
            repo_root=repo_layout.root,
            session_id="sess",
            actual_cwd=repo_layout.root,
        )
        assert outcome.ok is False
        assert outcome.block_kind == steps.BLOCK_PATH_CLAIM
        assert "claim 39 is blocked" in outcome.narrative

    def test_dirty_main_blocks_only_when_creating_new(
        self, tmp_path, monkeypatch
    ):
        # No worktree directory exists -> create path. Dirty main must block.
        import subprocess

        repo = tmp_path / "main"
        repo.mkdir()
        subprocess.run(
            ["git", "init", "--quiet", str(repo)], check=True, capture_output=True,
        )
        (repo / ".worktrees").mkdir(parents=True)
        _patch_steps(
            monkeypatch,
            dirty_outcome=(True, steps.BLOCK_DIRTY_TRACKED, ["foo.py"]),
        )
        outcome = wp.run_preflight(
            item_id=9001,
            repo_root=str(repo),
            session_id="sess",
            actual_cwd=str(repo),
        )
        assert outcome.ok is False
        assert outcome.block_kind == steps.BLOCK_DIRTY_TRACKED
        assert "foo.py" in outcome.narrative

    def test_dirty_main_does_not_block_re_entry(self, repo_layout, monkeypatch):
        # Worktree already exists -> reuse; dirty main is irrelevant.
        from yoke_core.domain import worktree_create
        _patch_steps(
            monkeypatch,
            dirty_outcome=(True, steps.BLOCK_DIRTY_TRACKED, ["foo.py"]),
            create_result=worktree_create.CreateWorktreeResult(
                path=repo_layout.worktree,
                branch="YOK-9001",
                created=False,
            ),
        )
        outcome = wp.run_preflight(
            item_id=9001,
            repo_root=repo_layout.root,
            session_id="sess",
            actual_cwd=repo_layout.root,
        )
        assert outcome.ok is True
        assert "worktree:reused" in outcome.actions_taken


class TestNoWorktreeMode:
    def test_no_worktree_skips_creation_and_scope(
        self, repo_layout, monkeypatch
    ):
        # If create_worktree is consulted with --no-worktree, that's a
        # logic error — the orchestrator must skip it entirely.
        from yoke_core.domain import worktree_create

        def _explode(**_kwargs):
            raise AssertionError("create_worktree must not be called when no_worktree=True")

        monkeypatch.setattr(worktree_create, "create_worktree", _explode)
        _patch_steps(monkeypatch)
        outcome = wp.run_preflight(
            item_id=9001,
            repo_root=repo_layout.root,
            session_id="sess",
            no_worktree=True,
        )
        assert outcome.ok is True
        assert outcome.semantic_scope == "main"
        assert "worktree:skipped" in outcome.actions_taken
        assert outcome.worktree_path == ""
        assert outcome.physical_cwd_mode == ""


class TestEnvelope:
    def test_ok_envelope_carries_operator_required_fields(self, repo_layout):
        outcome = wp.WorktreePreflightOutcome(
            ok=True,
            item_id=9001,
            branch="YOK-9001",
            worktree_path=repo_layout.worktree,
            semantic_scope="worktree",
            physical_cwd_mode=steps.CWD_MODE_STATIC,
            actions_taken=["work-claim:already-owned"],
            notes=["..."],
        )
        envelope = outcome.to_envelope()
        required = {
            "ok", "item_id", "branch", "worktree_path", "semantic_scope",
            "physical_cwd_mode", "actions_taken", "notes",
        }
        for field in (
            "item_id", "branch", "worktree_path", "semantic_scope",
            "physical_cwd_mode", "actions_taken",
            "notes",
        ):
            assert field in envelope, f"missing {field}"
        assert set(envelope) == required
        assert envelope["ok"] is True

    def test_block_envelope_carries_block_kind(self):
        outcome = wp.WorktreePreflightOutcome(
            ok=False,
            block_kind=steps.BLOCK_WORK_CLAIM,
            narrative="conflict",
            item_id=9001,
        )
        envelope = outcome.to_envelope()
        assert envelope == {
            "ok": False,
            "block_kind": steps.BLOCK_WORK_CLAIM,
            "narrative": "conflict",
            "item_id": 9001,
        }


class TestCli:
    def test_parse_item_id_strips_sun_prefix(self):
        assert wp._parse_item_id("YOK-1599") == 1599
        assert wp._parse_item_id("yok-9001") == 9001
        assert wp._parse_item_id("0042") == 42
        assert wp._parse_item_id("9001") == 9001

    def test_main_returns_2_on_invalid_item(self, capsys):
        rc = wp.main(["--item", "not-a-number"])
        assert rc == 2
        captured = capsys.readouterr()
        assert "Invalid --item" in captured.err

    def test_main_emits_envelope_json_on_success(
        self, repo_layout, monkeypatch, capsys
    ):
        from yoke_core.domain import worktree_create

        _patch_steps(
            monkeypatch,
            create_result=worktree_create.CreateWorktreeResult(
                path=repo_layout.worktree,
                branch="YOK-9001",
                created=False,
            ),
        )

        # Force orchestrator to use repo_layout.root rather than $PWD.
        monkeypatch.setattr(
            "yoke_core.domain.worktree_paths._resolve_repo_root_from_cwd",
            lambda: repo_layout.root,
        )
        monkeypatch.chdir(repo_layout.root)
        rc = wp.main(["--item", "YOK-9001", "--session-id", "sess"])
        assert rc == 0
        out = capsys.readouterr().out
        envelope = json.loads(out)
        assert envelope["ok"] is True
        assert envelope["item_id"] == 9001
        assert envelope["worktree_path"] == repo_layout.worktree
