"""The standalone-item merge boundary and its close-out ordering."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.standalone_merge_simulation_support import (
    git as _git,
    make_checkout,
    merge as _merge,
    stub_candidate_review,
    stub_receipts,
)
from yoke_core.domain import standalone_item_merge as sim
from yoke_core.domain import standalone_item_merge_cli as sim_cli
from yoke_core.domain import (
    standalone_item_merge_close_out_transition as close_out_transition,
)
from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute
from yoke_core.domain import standalone_item_merge_lane as sim_lane


@pytest.fixture(autouse=True)
def _no_control_plane(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_receipts(monkeypatch)
    stub_candidate_review(monkeypatch)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_checkout(tmp_path)


class TestMergeBoundary:
    def test_missing_branch_refuses_without_touching_the_checkout(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(sim, "stamp_merged_at", lambda item_id, **_kwargs: None)
        outcome = sim.merge_standalone_branch(
            project="yoke",
            item_id=1,
            branch="ITEM-404",
            target="main",
            repo_root=str(repo),
        )
        assert not outcome.ok
        assert "does not exist" in outcome.error

    def test_engine_failure_reports_without_stamping(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A refused merge must not record the item as merged."""
        stamped: list[int] = []
        monkeypatch.setattr(
            sim,
            "stamp_merged_at",
            lambda item_id, **_kwargs: stamped.append(item_id),
        )
        monkeypatch.setattr(
            sim,
            "_run_merge_engine",
            lambda **_kwargs: (1, "merge refused"),
        )
        outcome = _merge(repo)
        assert not outcome.ok
        assert outcome.exit_code == 1
        assert stamped == []

    def test_merge_lock_contention_is_reported_as_retryable(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(sim, "stamp_merged_at", lambda item_id, **_kwargs: None)
        monkeypatch.setattr(
            sim,
            "_run_merge_engine",
            lambda **_kwargs: (sim.RECOVERABLE_MERGE_LOCK_EXIT_CODE, ""),
        )
        outcome = _merge(repo)
        assert outcome.exit_code == sim.RECOVERABLE_MERGE_LOCK_EXIT_CODE
        assert "retry" in outcome.error

    def test_already_merged_branch_converges_instead_of_refusing(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A retry after a partial run stamps without re-running the engine."""
        _git(repo, "merge", "--no-edit", "ITEM-1")
        stamped: list[int] = []
        monkeypatch.setattr(
            sim,
            "stamp_merged_at",
            lambda item_id, **_kwargs: stamped.append(item_id),
        )
        monkeypatch.setattr(
            sim,
            "_run_merge_engine",
            lambda **_kwargs: pytest.fail("engine must not re-run"),
        )
        outcome = _merge(repo)
        assert outcome.ok
        assert outcome.already_merged
        assert stamped == [7]

    def test_touched_files_come_from_the_branch_itself(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(sim, "stamp_merged_at", lambda item_id, **_kwargs: None)
        monkeypatch.setattr(sim, "_run_merge_engine", lambda **_k: (0, ""))
        outcome = _merge(repo)
        assert outcome.touched_files == ("feature.txt",)
        assert outcome.commit_sha

    def test_a_checkout_with_no_remote_skips_publishing(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """External projects without a remote still complete the merge."""
        monkeypatch.setattr(sim, "stamp_merged_at", lambda item_id, **_kwargs: None)
        monkeypatch.setattr(sim, "_run_merge_engine", lambda **_k: (0, ""))
        outcome = _merge(repo)
        assert outcome.ok
        assert not outcome.pushed
        assert not outcome.warnings

    def test_a_failed_stamp_warns_rather_than_unwinding_the_merge(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            sim,
            "stamp_merged_at",
            lambda item_id, **_kwargs: "control plane refused",
        )
        monkeypatch.setattr(sim, "_run_merge_engine", lambda **_k: (0, ""))
        outcome = _merge(repo)
        assert outcome.ok
        assert any("merged_at" in warning for warning in outcome.warnings)


class TestCloseOutOrdering:
    def test_evidence_is_required_before_the_terminal_transition(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """An evidence-gated workflow refuses to close out with no summaries."""
        monkeypatch.setattr(
            sim_cli,
            "_resolve_item",
            lambda ref, project: (
                {
                    "id": 7,
                    "public_ref": "ITEM-1",
                    "status": "reviewing-implementation",
                    "workflow": {"id": "dash"},
                },
                "",
            ),
        )
        exit_code = sim_cli.run(["ITEM-1"])
        assert exit_code == 1
        assert "evidence-gated" in capsys.readouterr().err

    def test_skip_status_merges_without_requiring_evidence(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Deployment posture and multi-slice callers merge, then close out."""
        calls: list[str] = []
        monkeypatch.setattr(
            sim_cli,
            "_resolve_item",
            lambda ref, project: (
                {
                    "id": 7,
                    "public_ref": "ITEM-1",
                    "status": "reviewing-implementation",
                    "workflow": {"id": "dash"},
                    "worktrees": [{"commit_sha": _git(repo, "rev-parse", "ITEM-1")}],
                },
                "",
            ),
        )
        monkeypatch.setattr(sim_cli, "_session_holds_claim", lambda *_a: "")
        monkeypatch.setattr(
            sim_cli,
            "_resolve_checkout",
            lambda item, target: (repo, "main"),
        )

        def _enter_release(**kwargs):
            stages = tuple(kwargs.get("stages") or ())
            assert "done" not in stages
            assert stages == ("release",)
            return ("release", "")

        monkeypatch.setattr(
            sim_cli.close_out,
            "transition_to_done",
            _enter_release,
        )
        monkeypatch.setattr(
            sim_cli.evidence,
            "record",
            lambda **_k: pytest.fail("evidence must be left alone"),
        )
        monkeypatch.setattr(
            sim,
            "sync_item_to_github",
            lambda item_id: calls.append("sync"),
        )
        monkeypatch.setattr(sim, "stamp_merged_at", lambda item_id, **_kwargs: None)
        monkeypatch.setattr(sim, "_run_merge_engine", lambda **_k: (0, ""))

        assert sim_cli.run(["ITEM-1", "--skip-status"]) == 0
        assert calls == ["sync"]

    def test_a_refused_transition_leaves_the_recorded_evidence_intact(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A blocked gate reports; it never re-runs the merge or drops evidence."""
        monkeypatch.setattr(
            sim_cli,
            "_resolve_item",
            lambda ref, project: (
                {
                    "id": 7,
                    "public_ref": "ITEM-1",
                    "status": "reviewing-implementation",
                    "workflow": {"id": "dash"},
                    "worktrees": [{"commit_sha": _git(repo, "rev-parse", "ITEM-1")}],
                },
                "",
            ),
        )
        monkeypatch.setattr(sim_cli, "_session_holds_claim", lambda *_a: "")
        monkeypatch.setattr(
            sim_cli,
            "_resolve_checkout",
            lambda item, target: (repo, "main"),
        )
        monkeypatch.setattr(sim_cli.evidence, "record", lambda **_k: "")
        monkeypatch.setattr(
            close_out_transition,
            "close_out_route",
            lambda *_a, **_k: CloseOutRoute(stages=("done",)),
        )
        monkeypatch.setattr(
            sim_cli.close_out,
            "transition_to_done",
            lambda **_k: ("", "deployment run has not succeeded"),
        )
        monkeypatch.setattr(sim, "sync_item_to_github", lambda item_id: None)
        monkeypatch.setattr(sim, "stamp_merged_at", lambda item_id, **_kwargs: None)
        monkeypatch.setattr(sim, "_run_merge_engine", lambda **_k: (0, ""))

        exit_code = sim_cli.run(
            ["ITEM-1", "--result", "landed", "--verification", "suite green"],
        )
        assert exit_code == 1
        envelope = capsys.readouterr().out
        assert '"evidence_recorded": true' in envelope
        assert "deployment run has not succeeded" in envelope

    def test_a_session_without_the_item_claim_cannot_merge(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        monkeypatch.setattr(
            sim_cli,
            "_resolve_item",
            lambda ref, project: (
                {
                    "id": 7,
                    "public_ref": "ITEM-1",
                    "status": "reviewing-implementation",
                    "workflow": {"id": "dash"},
                },
                "",
            ),
        )
        monkeypatch.setattr(
            sim_cli,
            "_session_holds_claim",
            lambda *_a: "work claim held by another session (other)",
        )
        exit_code = sim_cli.run(
            ["ITEM-1", "--result", "landed", "--verification", "green"],
        )
        assert exit_code == 1
        assert "another session" in capsys.readouterr().err


class TestLaneBranchResolution:
    def test_the_registered_lane_branch_wins_over_the_item_ref(self) -> None:
        item = {"worktrees": [{"branch": "renamed-lane"}]}
        assert sim_lane.lane_branch(item, "ITEM-1") == "renamed-lane"

    def test_the_item_ref_is_the_fallback_branch_name(self) -> None:
        assert sim_lane.lane_branch({"worktrees": []}, "ITEM-1") == "ITEM-1"
