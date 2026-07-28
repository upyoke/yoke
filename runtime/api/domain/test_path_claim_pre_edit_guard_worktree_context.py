"""Pre-edit path-claim guard coverage for multi-lane worktree context."""

from yoke_core.domain.observe_normalization import TOOL_KIND_EDIT, ToolEventRecord
from yoke_core.domain.path_claim_pre_edit_guard import evaluate_payload


class TestLiveNoConnEpicResolution:
    def test_lanes_allow_and_deny_carries_effective_wt(self, tmp_path, live_db):
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

        def record(target, cwd):
            return ToolEventRecord(
                tool_kind=TOOL_KIND_EDIT,
                changed_paths=[target],
                tool_name="Edit",
                session_id="engineer-1",
                cwd=cwd,
            )

        a = str(repo / ".worktrees/lane-a/runtime/api/domain/a.py")
        b = str(repo / ".worktrees/lane-b/runtime/api/domain/b.py")
        assert (
            evaluate_payload(record(a, str(repo / ".worktrees/lane-a"))).outcome
            == "allow"
        )
        assert (
            evaluate_payload(record(b, str(repo / ".worktrees/lane-b"))).outcome
            == "allow"
        )
        deny_target = str(repo / ".worktrees/lane-a/docs/never-covered.md")
        verdict = evaluate_payload(
            record(deny_target, str(repo / ".worktrees/lane-a"))
        )
        assert verdict.outcome == "deny"
        assert verdict.failure_mode == "out-of-claim"
        expected_worktree = verdict.extra.get("expected_worktree_path")
        assert expected_worktree is not None and "lane-a" in expected_worktree
