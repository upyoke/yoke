"""Preparation envelopes carry public identity on success and refusal."""

from runtime.api.domain.test_worktree_preflight import repo_layout as repo_layout
from yoke_core.domain import worktree_preflight as wp
from yoke_core.domain import worktree_preflight_steps as steps


class TestEnvelope:
    def test_ok_envelope_carries_operator_required_fields(self, repo_layout):
        outcome = wp.WorktreePreflightOutcome(
            ok=True,
            public_ref="YOK-9001",
            branch="YOK-9001",
            worktree_path=repo_layout.worktree,
            semantic_scope="worktree",
            physical_cwd_mode=steps.CWD_MODE_STATIC,
            actions_taken=["work-claim:already-owned"],
            notes=["..."],
        )
        envelope = outcome.to_envelope()
        required = {
            "ok",
            "public_ref",
            "branch",
            "worktree_path",
            "semantic_scope",
            "physical_cwd_mode",
            "actions_taken",
            "notes",
        }
        for field in (
            "public_ref",
            "branch",
            "worktree_path",
            "semantic_scope",
            "physical_cwd_mode",
            "actions_taken",
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
            public_ref="YOK-9001",
        )
        envelope = outcome.to_envelope()
        assert envelope == {
            "ok": False,
            "block_kind": steps.BLOCK_WORK_CLAIM,
            "narrative": "conflict",
            "public_ref": "YOK-9001",
        }
