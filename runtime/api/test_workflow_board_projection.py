"""Pinned workflow board projection and refusal to infer missing metadata."""

from __future__ import annotations

from yoke_core.domain.board import UNKNOWN_BUCKET, status_to_board_bucket


class TestWorkflowBoardProjection:
    def test_arbitrary_stage_ids_follow_declared_skill_segments(self):
        stage_ids = (
            "captured",
            "shaping",
            "ready-to-build",
            "building",
            "quality-review",
            "quality-approved",
            "finishing",
            "ready-to-ship",
            "shipping",
            "closed",
        )
        definition = {
            "stages": [{"id": stage_id} for stage_id in stage_ids],
            "terminal_stage_ids": ["closed"],
            "skill_bindings": [
                {
                    "skill_id": "refine",
                    "from_stage_id": "captured",
                    "through_stage_id": "ready-to-build",
                },
                {
                    "skill_id": "implement",
                    "from_stage_id": "ready-to-build",
                    "through_stage_id": "quality-approved",
                },
                {
                    "skill_id": "polish",
                    "from_stage_id": "quality-approved",
                    "through_stage_id": "ready-to-ship",
                },
                {
                    "skill_id": "usher",
                    "from_stage_id": "ready-to-ship",
                    "through_stage_id": "closed",
                },
            ],
            "policies": {"generated_children": "none"},
        }

        assert (
            status_to_board_bucket("shaping", workflow_definition=definition)
            == "planning"
        )
        assert (
            status_to_board_bucket("ready-to-build", workflow_definition=definition)
            == "refined"
        )
        assert (
            status_to_board_bucket("building", workflow_definition=definition)
            == "implementing"
        )
        assert (
            status_to_board_bucket("quality-review", workflow_definition=definition)
            == "reviewing"
        )
        assert (
            status_to_board_bucket("finishing", workflow_definition=definition)
            == "reviewing"
        )
        assert (
            status_to_board_bucket("ready-to-ship", workflow_definition=definition)
            == "implemented"
        )
        assert (
            status_to_board_bucket("shipping", workflow_definition=definition)
            == "release"
        )
        assert (
            status_to_board_bucket("closed", workflow_definition=definition) == "done"
        )

    def test_no_item_type_legacy_active_is_unknown(self):
        """Legacy active status no longer has a compatibility mapping."""
        assert status_to_board_bucket("active") == UNKNOWN_BUCKET

    def test_epic_active_no_override(self):
        """Epic + legacy active has no compatibility override."""
        assert status_to_board_bucket("active", workflow_id="epic") == UNKNOWN_BUCKET

    def test_issue_implementing_no_override(self):
        """Workflow identity alone supplies no stage semantics."""
        assert (
            status_to_board_bucket("implementing", workflow_id="issue")
            == UNKNOWN_BUCKET
        )


def test_terminal_name_without_a_pin_is_unknown():
    assert status_to_board_bucket("done") == UNKNOWN_BUCKET
    assert status_to_board_bucket("release") == UNKNOWN_BUCKET
