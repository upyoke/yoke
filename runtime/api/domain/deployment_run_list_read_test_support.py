# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from unittest.mock import patch

import pytest

from yoke_core.domain.deployment_run_list_read import (
    _member_items,
    _stage_rows,
    list_deployment_runs,
)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _RunRows:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def close(self):
        return None

    def execute(self, sql, _params):
        if "pg_catalog.pg_attribute" in sql:
            return _Result([{"name": "present"}])
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
