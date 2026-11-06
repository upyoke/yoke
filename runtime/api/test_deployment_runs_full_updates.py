# ruff: noqa: F811
"""Deployment-run status update and timestamp tests."""

from runtime.api.deployment_runs_full_helpers_test_support import (_conn as _conn, db_path as db_path)
from runtime.api.domain.worktree_create_test_support import (_placeholder as _placeholder)

from yoke_core.domain import deployment_runs as dr


class TestUpdate:
    """cmd_update: status transitions, auto-timestamps, validation."""


    def test_update_current_stage(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        err = dr.cmd_update(rid, "current_stage", "smoke", db_path=db_path)
        assert err is None
        assert dr.cmd_get(rid, field="current_stage", db_path=db_path) == "smoke"
