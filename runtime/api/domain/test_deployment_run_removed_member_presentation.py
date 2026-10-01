"""Removed custody stays visible without pretending its cancelled QA passed."""

import json
from unittest.mock import patch

import pytest

from yoke_core.domain.deployment_run_list_read import present_deployment_runs
from yoke_core.domain.deployment_run_member_presentation import removed_member_items
from yoke_core.domain.deployment_run_membership_removals import (
    parse_membership_removals,
)


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class Database:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if "FROM items i" in sql:
            return Rows(
                [
                    {
                        "id": 7,
                        "project_id": 1,
                        "project_sequence": 3,
                        "project": "sample",
                        "public_item_prefix": "ITEM",
                        "title": "Removed work",
                    }
                ]
            )
        return Rows(
            [
                {"item_id": 7, "id": "run-later", "created_at": "2026-10-02"},
                {"item_id": 7, "id": "run-before", "created_at": "2026-09-01"},
            ]
        )


def run():
    return {
        "id": "run-original",
        "created_at": "2026-10-01",
        "status": "succeeded",
        "membership_removals": json.dumps(
            [{"item_id": 7, "reason": "needs correction"}]
        ),
    }


def test_removed_record_resolves_identity_and_current_newer_custody():
    database = Database()
    result = removed_member_items(database, [run()], visible_project_ids={1})
    item = result["run-original"][0]
    assert item["ref"] == "ITEM-3"
    assert item["reason"] == "needs correction"
    assert item["later_run_id"] == "run-later"
    assert "i.project_id IN" in database.calls[0][0]
    assert database.calls[0][1] == (7, 1)
    assert "NOT IN ('failed', 'cancelled')" in database.calls[1][0]


def test_removed_record_without_newer_custody_leaves_destination_unknown():
    source = {**run(), "created_at": "2026-10-03"}
    assert (
        removed_member_items(Database(), [source])["run-original"][0]["later_run_id"]
        is None
    )


def test_no_removals_or_no_visible_projects_needs_no_database_read():
    database = Database()
    assert removed_member_items(database, [{"id": "empty"}]) == {}
    assert removed_member_items(database, [run()], visible_project_ids=set()) == {}
    assert database.calls == []


def test_unreadable_removal_record_names_run_and_recovery():
    with pytest.raises(ValueError, match="run-original.*repair it to a JSON array"):
        parse_membership_removals("{}", "run-original")


def test_presenter_removes_stale_members_before_loading_qa_and_preserves_notice():
    database = Database()
    with (
        patch(
            "yoke_core.domain.deployment_run_list_read._member_items",
            return_value={"run-original": [{"id": 7}]},
        ),
        patch("yoke_core.domain.deployment_run_list_read.run_gates", return_value={}),
        patch(
            "yoke_core.domain.deployment_run_list_read.candidate_delivery_items",
            return_value={},
        ),
        patch(
            "yoke_core.domain.deployment_qa_run_acceptance.member_qa_standings",
            return_value={},
        ) as qa,
    ):
        result = present_deployment_runs(
            database,
            [run()],
            actor_id=None,
            visible_project_ids={1},
            include_carried_work=True,
            compact=True,
            include_item_delivery=True,
        )[0]
    assert result["member_items"] == []
    assert result["removed_member_items"][0]["later_run_id"] == "run-later"
    assert "membership_removals" not in result
    assert qa.call_args.args[1] == []
