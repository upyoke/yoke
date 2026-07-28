# ruff: noqa: F811
"""Deployment-run status update and timestamp tests."""

from yoke_core.domain import deployment_runs as dr
from runtime.api.test_deployment_runs_full_helpers import (  # noqa: F401
    _conn,
    _placeholder,
    db_path,
)


class TestUpdate:
    """cmd_update: status transitions, auto-timestamps, validation."""

    def test_update_status_executing(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        err = dr.cmd_update(rid, "status", "executing", db_path=db_path)
        assert err is None
        assert dr.cmd_get(rid, field="status", db_path=db_path) == "executing"

    def test_executing_sets_started_at(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_update(rid, "status", "executing", db_path=db_path)
        conn = _conn(db_path)
        p = _placeholder(conn)
        started = conn.execute(
            f"SELECT started_at FROM deployment_runs WHERE id={p}", (rid,)
        ).fetchone()[0]
        conn.close()
        assert started is not None

    def test_terminal_status_sets_completed_at(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_update(rid, "status", "failed", db_path=db_path)
        conn = _conn(db_path)
        p = _placeholder(conn)
        completed = conn.execute(
            f"SELECT completed_at FROM deployment_runs WHERE id={p}", (rid,)
        ).fetchone()[0]
        conn.close()
        assert completed is not None

    def test_update_current_stage(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        err = dr.cmd_update(rid, "current_stage", "smoke", db_path=db_path)
        assert err is None
        assert dr.cmd_get(rid, field="current_stage", db_path=db_path) == "smoke"

    def test_update_invalid_status(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        err = dr.cmd_update(rid, "status", "bogus", db_path=db_path)
        assert err is not None
        assert "invalid status" in err

    def test_update_non_updatable_field(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        err = dr.cmd_update(rid, "id", "new-id", db_path=db_path)
        assert err is not None
        assert "not updatable" in err

    def test_update_not_found(self, db_path):
        err = dr.cmd_update("nonexistent", "status", "executing", db_path=db_path)
        assert err is not None
        assert "not found" in err

    def test_succeeded_rejects_failed_stage(self, db_path):
        """status=succeeded rejected if current_stage ends in -failed."""
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_update(rid, "current_stage", "deploy-failed", db_path=db_path)
        err = dr.cmd_update(rid, "status", "succeeded", db_path=db_path)
        assert err is not None
        assert "failure" in err.lower() or "failed" in err.lower()

    def test_succeeded_rejects_non_final_stage(self, db_path):
        """status=succeeded rejected if not on final flow stage."""
        rid = dr.cmd_create_run(
            "externalwebapp", "externalwebapp-standard", db_path=db_path
        )
        dr.cmd_update(rid, "current_stage", "preview", db_path=db_path)
        err = dr.cmd_update(rid, "status", "succeeded", db_path=db_path)
        assert err is not None
        assert "not the final stage" in err

    def test_succeeded_accepts_final_stage(self, db_path):
        """status=succeeded accepted when on final stage."""
        rid = dr.cmd_create_run(
            "externalwebapp", "externalwebapp-standard", db_path=db_path
        )
        dr.cmd_update(rid, "current_stage", "production", db_path=db_path)
        err = dr.cmd_update(rid, "status", "succeeded", db_path=db_path)
        assert err is None

    def test_succeeded_force_overrides_guard(self, db_path):
        """force=True bypasses the stage guard."""
        rid = dr.cmd_create_run(
            "externalwebapp", "externalwebapp-standard", db_path=db_path
        )
        dr.cmd_update(rid, "current_stage", "deploy-failed", db_path=db_path)
        err = dr.cmd_update(rid, "status", "succeeded", force=True, db_path=db_path)
        assert err is None
