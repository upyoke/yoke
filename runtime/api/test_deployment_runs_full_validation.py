"""Composition + batch-compatibility tests for deployment_runs.

Covers cmd_validate_composition and cmd_check_batch_compatibility.

Split from ``test_deployment_runs_full.py``.
"""

from __future__ import annotations

from yoke_core.domain import db_backend
from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from runtime.api.test_deployment_runs_full_helpers import db_path, _conn  # noqa: F401


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _upsert_item_sql(conn) -> str:
    p = _p(conn)
    return (
        "INSERT INTO items "
        "(id, title, status, project_id, project_sequence, deployment_flow, "
        "created_at, updated_at) "
        f"VALUES ({p}, 'test', {p}, {p}, {p}, {p}, {p}, {p}) "
        "ON CONFLICT (id) DO UPDATE SET "
        "title = excluded.title, status = excluded.status, "
        "project_id = excluded.project_id, "
        "project_sequence = excluded.project_sequence, "
        "deployment_flow = excluded.deployment_flow, "
        "created_at = excluded.created_at, updated_at = excluded.updated_at"
    )


def _project_id(project: str) -> int:
    return SEED_PROJECT_IDS[project]


class TestValidateComposition:
    """cmd_validate_composition: project, flow, status, dependency checks."""

    def _insert_item(self, db_path, item_id, status="implemented", project="yoke", flow=None):
        conn = _conn(db_path)
        conn.execute(
            _upsert_item_sql(conn),
            (
                item_id,
                status,
                _project_id(project),
                item_id,
                flow,
                "2026-04-20T00:00:00Z",
                "2026-04-20T00:00:00Z",
            ),
        )
        conn.commit()
        conn.close()

    def test_valid_composition(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        self._insert_item(db_path, 100, "implemented")
        self._insert_item(db_path, 200, "release")
        dr.cmd_add_item(rid, 100, db_path=db_path)
        dr.cmd_add_item(rid, 200, db_path=db_path)

        ok, msg = dr.cmd_validate_composition(rid, db_path=db_path)
        assert ok is True
        assert msg == "OK"

    def test_run_not_found(self, db_path):
        ok, msg = dr.cmd_validate_composition("nonexistent", db_path=db_path)
        assert ok is False
        assert "not found" in msg

    def test_wrong_project(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        self._insert_item(db_path, 100, "implemented", project="externalwebapp")
        dr.cmd_add_item(rid, 100, db_path=db_path)

        ok, msg = dr.cmd_validate_composition(rid, db_path=db_path)
        assert ok is False
        assert "Project mismatch" in msg

    def test_wrong_flow(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        self._insert_item(db_path, 100, "implemented", flow="other-flow")
        dr.cmd_add_item(rid, 100, db_path=db_path)

        ok, msg = dr.cmd_validate_composition(rid, db_path=db_path)
        assert ok is False
        assert "Incompatible deployment flow" in msg

    def test_item_not_at_implemented(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        self._insert_item(db_path, 100, "idea")
        dr.cmd_add_item(rid, 100, db_path=db_path)

        ok, msg = dr.cmd_validate_composition(rid, db_path=db_path)
        assert ok is False
        assert "not at implemented" in msg

    def test_done_items_accepted(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        self._insert_item(db_path, 100, "done")
        dr.cmd_add_item(rid, 100, db_path=db_path)

        ok, msg = dr.cmd_validate_composition(rid, db_path=db_path)
        assert ok is True

    def test_unsatisfied_dependency(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        self._insert_item(db_path, 100, "implemented")
        self._insert_item(db_path, 200, "idea")  # blocker not done
        dr.cmd_add_item(rid, 100, db_path=db_path)

        conn = _conn(db_path)
        conn.execute(
            "INSERT INTO item_dependencies (dependent_item, blocking_item, satisfaction, source, created_at) "
            "VALUES ('YOK-100', 'YOK-200', 'status:done', 'test', '2026-04-20T00:00:00Z')"
        )
        conn.commit()
        conn.close()

        ok, msg = dr.cmd_validate_composition(rid, db_path=db_path)
        assert ok is False
        assert "Unsatisfied" in msg

    def test_coordination_only_dependency_ignored(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        self._insert_item(db_path, 100, "implemented")
        self._insert_item(db_path, 200, "idea")
        dr.cmd_add_item(rid, 100, db_path=db_path)

        conn = _conn(db_path)
        conn.execute(
            "INSERT INTO item_dependencies "
            "(dependent_item, blocking_item, gate_point, satisfaction, source, created_at) "
            "VALUES ('YOK-100', 'YOK-200', 'coordination_only', 'fact:merged', 'test', "
            "'2026-04-20T00:00:00Z')"
        )
        conn.commit()
        conn.close()

        ok, msg = dr.cmd_validate_composition(rid, db_path=db_path)
        assert ok is True
        assert msg == "OK"

    def test_satisfied_dependency_done(self, db_path):
        """Blocker with status:done satisfaction that is done passes."""
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        self._insert_item(db_path, 100, "implemented")
        self._insert_item(db_path, 200, "done")
        dr.cmd_add_item(rid, 100, db_path=db_path)

        conn = _conn(db_path)
        conn.execute(
            "INSERT INTO item_dependencies (dependent_item, blocking_item, satisfaction, source, created_at) "
            "VALUES ('YOK-100', 'YOK-200', 'status:done', 'test', '2026-04-20T00:00:00Z')"
        )
        conn.commit()
        conn.close()

        ok, msg = dr.cmd_validate_composition(rid, db_path=db_path)
        assert ok is True

    def test_blocker_in_run_passes(self, db_path):
        """If the blocker is also in the run, composition is valid."""
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        self._insert_item(db_path, 100, "implemented")
        self._insert_item(db_path, 200, "implemented")
        dr.cmd_add_item(rid, 100, db_path=db_path)
        dr.cmd_add_item(rid, 200, db_path=db_path)

        conn = _conn(db_path)
        conn.execute(
            "INSERT INTO item_dependencies (dependent_item, blocking_item, satisfaction, source, created_at) "
            "VALUES ('YOK-100', 'YOK-200', 'status:done', 'test', '2026-04-20T00:00:00Z')"
        )
        conn.commit()
        conn.close()

        ok, msg = dr.cmd_validate_composition(rid, db_path=db_path)
        assert ok is True


class TestCheckBatchCompatibility:
    """cmd_check_batch_compatibility: pre-run validation."""

    def _insert_item(self, db_path, item_id, status="implemented", project="yoke", flow=None):
        conn = _conn(db_path)
        conn.execute(
            _upsert_item_sql(conn),
            (
                item_id,
                status,
                _project_id(project),
                item_id,
                flow,
                "2026-04-20T00:00:00Z",
                "2026-04-20T00:00:00Z",
            ),
        )
        conn.commit()
        conn.close()

    def test_valid_batch(self, db_path):
        self._insert_item(db_path, 100, "implemented")
        self._insert_item(db_path, 200, "release")
        ok, msg = dr.cmd_check_batch_compatibility(
            "yoke", "yoke-internal", [100, 200], db_path=db_path,
        )
        assert ok is True
        assert msg == "OK"

    def test_empty_batch(self, db_path):
        ok, msg = dr.cmd_check_batch_compatibility(
            "yoke", "yoke-internal", [], db_path=db_path,
        )
        assert ok is False
        assert "No item IDs" in msg

    def test_wrong_project_in_batch(self, db_path):
        self._insert_item(db_path, 100, "implemented", project="externalwebapp")
        ok, msg = dr.cmd_check_batch_compatibility(
            "yoke", "yoke-internal", [100], db_path=db_path,
        )
        assert ok is False
        assert "Project mismatch" in msg

    def test_wrong_flow_in_batch(self, db_path):
        self._insert_item(db_path, 100, "implemented", flow="other-flow")
        ok, msg = dr.cmd_check_batch_compatibility(
            "yoke", "yoke-internal", [100], db_path=db_path,
        )
        assert ok is False
        assert "Incompatible deployment flow" in msg

    def test_item_not_implemented_in_batch(self, db_path):
        self._insert_item(db_path, 100, "idea")
        ok, msg = dr.cmd_check_batch_compatibility(
            "yoke", "yoke-internal", [100], db_path=db_path,
        )
        assert ok is False
        assert "not at implemented" in msg

    def test_unsatisfied_dep_in_batch(self, db_path):
        self._insert_item(db_path, 100, "implemented")
        self._insert_item(db_path, 200, "idea")  # blocker not done, outside batch

        conn = _conn(db_path)
        conn.execute(
            "INSERT INTO item_dependencies (dependent_item, blocking_item, satisfaction, source, created_at) "
            "VALUES ('YOK-100', 'YOK-200', 'status:done', 'test', '2026-04-20T00:00:00Z')"
        )
        conn.commit()
        conn.close()

        ok, msg = dr.cmd_check_batch_compatibility(
            "yoke", "yoke-internal", [100], db_path=db_path,
        )
        assert ok is False
        assert "Unsatisfied" in msg

    def test_coordination_only_dep_in_batch_ignored(self, db_path):
        self._insert_item(db_path, 100, "implemented")
        self._insert_item(db_path, 200, "idea")

        conn = _conn(db_path)
        conn.execute(
            "INSERT INTO item_dependencies "
            "(dependent_item, blocking_item, gate_point, satisfaction, source, created_at) "
            "VALUES ('YOK-100', 'YOK-200', 'coordination_only', 'fact:merged', 'test', "
            "'2026-04-20T00:00:00Z')"
        )
        conn.commit()
        conn.close()

        ok, msg = dr.cmd_check_batch_compatibility(
            "yoke", "yoke-internal", [100], db_path=db_path,
        )
        assert ok is True
        assert msg == "OK"
