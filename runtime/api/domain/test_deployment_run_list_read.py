"""Deployment-run member and segmented-stage projection helpers."""

from unittest.mock import patch

from yoke_core.domain.deployment_run_list_read import (
    _member_items,
    _stage_rows,
    list_deployment_runs,
)


class _MemberRows:
    def execute(self, _sql, _params):
        return self

    def fetchall(self):
        return [
            {
                "run_id": "run-20260819-001",
                "id": 2262,
                "title": "Ship the release",
                "status": "implemented",
                "project_sequence": 2228,
                "project_id": 1,
                "project": "yoke",
                "public_item_prefix": "YOK",
            }
        ]


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _RunRows:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def close(self):
        return None

    def execute(self, sql, _params):
        if "FROM deployment_runs dr" in sql:
            return _Result(
                [
                    {
                        "id": "run-20260819-002",
                        "project": "yoke",
                        "flow": "release",
                        "target_tier": "persistent",
                        "target_environment": "prod",
                        "release_lineage": "a" * 40,
                        "status": "succeeded",
                        "current_stage": "complete",
                        "created_at": "2026-08-19T00:00:00Z",
                        "started_at": "2026-08-19T00:01:00Z",
                        "completed_at": "2026-08-19T00:02:00Z",
                        "created_by": "operator",
                        "carried_work": '{"schema":1,"items":[],"commits":["abc"]}',
                        "stages": "[]",
                    }
                ]
            )
        return _Result([])


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


def test_run_list_exposes_carried_work_as_a_structured_object():
    with patch(
        "yoke_core.domain.deployment_run_list_read.connect",
        return_value=_RunRows(),
    ):
        rows = list_deployment_runs(project=None, status=None, limit=1)

    assert rows[0]["carried_work"] == {
        "schema": 1,
        "items": [],
        "commits": ["abc"],
    }
