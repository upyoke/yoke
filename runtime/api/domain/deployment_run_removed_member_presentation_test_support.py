# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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
        if "AS cancelled" in sql:
            return Rows(
                [{"deployment_run_id": "run-original", "item_id": 7, "cancelled": 2}]
            )
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
                {
                    "item_id": 7,
                    "id": "run-later",
                    "created_at": "2026-10-02T00:00:00.000000Z",
                },
                {
                    "item_id": 7,
                    "id": "run-before",
                    "created_at": "2026-09-01T00:00:00.000000Z",
                },
            ]
        )


def run():
    return {
        "id": "run-original",
        "created_at": "2026-10-01T00:00:00.000000Z",
        "status": "succeeded",
        "carried_work": json.dumps({"items": []}),
        "membership_removals": json.dumps(
            [{"item_id": 7, "reason": "needs correction"}]
        ),
    }
