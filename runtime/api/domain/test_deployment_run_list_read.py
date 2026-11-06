"""Deployment-run member and segmented-stage projection helpers."""

from runtime.api.domain.deployment_run_list_read_test_support import (
    _Result as _Result,
    _RunRows as _RunRows,
)


from unittest.mock import patch

import pytest

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
    assert rows[0]["overview_priority"] == 2


def test_overview_members_keep_their_own_qa_even_in_compact_presentation():
    from yoke_core.domain.deployment_run_list_read import present_deployment_runs

    members = {
        "run-batch": [
            {
                "id": 51,
                "ref": "ITEM-1",
                "status": "done",
                "title": "first",
                "project_id": 1,
                "project_sequence": 1,
            },
            {
                "id": 52,
                "ref": "ITEM-2",
                "status": "release",
                "title": "second",
                "project_id": 1,
                "project_sequence": 2,
            },
        ]
    }
    accepted = {"state": "accepted", "failed_requirement_ids": []}
    rejected = {"state": "cases unresolved", "failed_requirement_ids": [91]}
    with (
        patch(
            "yoke_core.domain.completed_item_delivery.completed_deliveries",
            return_value={},
        ),
        patch(
            "yoke_core.domain.deployment_run_list_read._member_items",
            return_value=members,
        ),
        patch("yoke_core.domain.deployment_run_list_read.run_gates", return_value={}),
        patch(
            "yoke_core.domain.deployment_run_list_read.candidate_delivery_items",
            return_value={},
        ),
        patch(
            "yoke_core.domain.deployment_qa_run_acceptance.member_qa_standings",
            return_value={("run-batch", 51): accepted, ("run-batch", 52): rejected},
        ) as read,
    ):
        rows = present_deployment_runs(
            object(),
            [
                {
                    "id": "run-batch",
                    "current_stage": "item-qa",
                    "status": "executing",
                    "stages": '["item-qa"]',
                }
            ],
            actor_id=None,
            visible_project_ids=None,
            include_carried_work=False,
            compact=True,
            include_item_delivery=True,
        )
    assert [member["item_qa"] for member in rows[0]["member_items"]] == [
        accepted,
        rejected,
    ]
    assert read.call_args.args[1] == [
        ("run-batch", 51, "item-qa"),
        ("run-batch", 52, "item-qa"),
    ]


def test_executing_memberless_run_exposes_current_carried_work_in_both_views():
    from yoke_core.domain.deployment_run_list_read import present_deployment_runs

    conn = _RunRows()
    base = [
        {
            "id": "run-stage",
            "status": "executing",
            "target_environment": "stage",
            "carried_work": None,
            "stages": "[]",
        }
    ]
    carried = {"items": [{"ref": "ITEM-1", "item_id": 10, "project_sequence": 1}]}
    with patch(
        "yoke_core.domain.deployment_run_carried_work_read.derive_carried_work_safely",
        return_value=carried,
    ):
        for compact in (False, True):
            rows = present_deployment_runs(
                conn,
                base,
                actor_id=None,
                visible_project_ids=None,
                include_carried_work=True,
                compact=compact,
            )
            assert rows[0]["carried_work"]["items"] == carried["items"]
            assert rows[0]["member_items"] == []
    assert base[0]["carried_work"] is None


@pytest.mark.parametrize("relevance", ["all", "overview"])
def test_run_lists_exclude_driver_receipt_at_query_time(relevance):
    from yoke_core.domain.deployment_runs_schema import _run_named_columns

    queries = []

    class RecordingRows(_RunRows):
        def execute(self, sql, params):
            queries.append(sql)
            return super().execute(sql, params)

    with patch(
        "yoke_core.domain.deployment_run_list_read.connect",
        return_value=RecordingRows(),
    ):
        list_deployment_runs(project=None, status=None, limit=20, relevance=relevance)
    select = next(sql for sql in queries if "FROM deployment_runs dr" in sql)
    assert "- 'preparation_receipt'" in select
    # Detail/recovery keeps the full stored binding through the default projection.
    detail_columns, _ = _run_named_columns()
    assert "- 'preparation_receipt'" not in detail_columns
