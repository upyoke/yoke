"""Deployment-run member and segmented-stage projection helpers."""

from yoke_core.domain.deployment_run_list_read import _member_items, _stage_rows


class _MemberRows:
    def execute(self, _sql, _params):
        return self

    def fetchall(self):
        return [{
            "run_id": "run-20260819-001",
            "id": 2262,
            "title": "Ship the release",
            "status": "implemented",
            "project_sequence": 2228,
            "project_id": 1,
            "project": "yoke",
            "public_item_prefix": "YOK",
        }]


def test_member_items_expose_route_sequence_separately_from_internal_id():
    result = _member_items(_MemberRows(), ["run-20260819-001"])
    member = result["run-20260819-001"][0]
    assert member["id"] == 2262
    assert member["ref"] == "YOK-2228"
    assert member["project_sequence"] == 2228


def test_executing_stage_marks_prior_complete_and_current_active():
    rows, index = _stage_rows(
        ["build", "verify", "release"],
        current="verify",
        status="executing",
    )
    assert index == 1
    assert rows == [
        {"name": "build", "state": "complete"},
        {"name": "verify", "state": "active"},
        {"name": "release", "state": "pending"},
    ]


def test_failed_and_succeeded_runs_project_terminal_stage_states():
    failed, _ = _stage_rows(
        ["build", "verify"],
        current="verify",
        status="failed",
    )
    assert [row["state"] for row in failed] == ["complete", "failed"]
    succeeded, succeeded_index = _stage_rows(
        ["build", "verify"],
        current="complete",
        status="succeeded",
    )
    assert [row["state"] for row in succeeded] == ["complete", "complete"]
    assert succeeded_index == 1
