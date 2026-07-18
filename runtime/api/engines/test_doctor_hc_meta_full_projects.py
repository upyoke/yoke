"""Doctor HC tests (Project FK/JSON/missing-flow/dependency HCs).

Other doctor_hc_meta_full tests live in sibling files.

Schema scaffolding shared via _doctor_hc_meta_full_test_helpers (private module).
Uses disposable Postgres test databases and mock subprocess for deterministic testing.
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_cancelled_blocker_dependencies,
    hc_dependency_drift,
    hc_duplicate_projects,
    hc_missing_flow,
    hc_null_project_items,
    hc_project_fk_integrity,
    hc_project_json_validity,
    hc_projects_without_flows,
)

from yoke_core.engines._doctor_hc_meta_full_test_helpers import (
    _args,
    _completed,
    _insert_deployment_flow,
    _insert_item,
    _iso_days_ago,
    _iso_minutes_ago,
    _make_conn,
    _p,
    _project_id,
    _result,
    _results,
    _run_hc,
    _seed_project,
)


class TestProjectFkIntegrityMeta:
    """HC-project-fk-integrity."""

    def test_pass_valid_project(self):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, 1)
        rec = _run_hc(hc_project_fk_integrity, conn)
        assert _result(rec).result == "PASS"

    def test_fail_invalid_project(self):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, 1, project="nonexistent")
        rec = _run_hc(hc_project_fk_integrity, conn)
        assert _result(rec).result == "FAIL"


class TestProjectJsonValidityMeta:
    """HC-project-json-validity.

    Retired project-context JSON columns moved into the ``context_routing``
    Project Structure family, where payloads are validated structurally on
    every write. The HC is now a no-op PASS when the projects table exists.
    """

    def test_pass_when_table_exists(self):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        rec = _run_hc(hc_project_json_validity, conn)
        assert _result(rec).result == "PASS"


class TestProjectsWithoutFlowsMeta:
    """HC-projects-without-flows."""

    def test_pass_has_flow(self):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_deployment_flow(conn, "f1")
        _insert_deployment_flow(conn, "externalwebapp-flow", project="externalwebapp")
        rec = _run_hc(hc_projects_without_flows, conn)
        assert _result(rec).result == "PASS"

    def test_warn_no_flows(self):
        conn = _make_conn()
        _seed_project(conn, "orphan")
        rec = _run_hc(hc_projects_without_flows, conn)
        assert _result(rec).result == "WARN"


class TestDuplicateProjectsMeta:
    """HC-duplicate-projects."""

    def test_pass_unique(self):
        conn = _make_conn()
        _seed_project(conn, "a", "A", "/a")
        _seed_project(conn, "b", "B", "/b")
        rec = _run_hc(hc_duplicate_projects, conn)
        assert _result(rec).result == "PASS"

    def test_shared_checkout_paths_are_not_project_identity(self):
        conn = _make_conn()
        _seed_project(conn, "a", "A", "/same")
        _seed_project(conn, "b", "B", "/same")
        rec = _run_hc(hc_duplicate_projects, conn)
        assert _result(rec).result == "PASS"

    def test_warn_duplicate_public_item_prefix(self):
        conn = _make_conn()
        _seed_project(conn, "a", "A", "/a", public_item_prefix="TST")
        _seed_project(conn, "b", "B", "/b", public_item_prefix="TST")
        rec = _run_hc(hc_duplicate_projects, conn)
        res = _result(rec)
        assert res.result == "WARN"
        assert "public_item_prefix 'TST'" in res.detail


class TestNullProjectItemsMeta:
    """HC-null-project-items."""

    def test_pass_all_have_project(self):
        conn = _make_conn()
        _insert_item(conn, 1, status="idea")
        rec = _run_hc(hc_null_project_items, conn)
        assert _result(rec).result == "PASS"

    def test_fail_null_project(self):
        conn = _make_conn()
        _insert_item(conn, 1, project=None, status="idea")
        rec = _run_hc(hc_null_project_items, conn)
        assert _result(rec).result == "FAIL"


class TestMissingFlowMeta:
    """HC-missing-flow."""

    def test_pass_has_flow(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, deployment_flow) "
            "VALUES (1, 'Test', 'implementing', 'flow-1')"
        )
        rec = _run_hc(hc_missing_flow, conn)
        assert _result(rec).result == "PASS"

    def test_warn_missing_flow(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, deployment_flow) "
            "VALUES (1, 'Test', 'implementing', NULL)"
        )
        rec = _run_hc(hc_missing_flow, conn)
        assert _result(rec).result == "WARN"


class TestDependencyDriftMeta:
    """HC-dependency-drift."""

    def test_pass_no_depends_on(self):
        conn = _make_conn()
        rec = _run_hc(hc_dependency_drift, conn)
        assert _result(rec).result == "PASS"


class TestCancelledBlockerDependenciesMeta:
    """HC-cancelled-blocker-dependencies."""

    def test_pass_no_rows(self):
        conn = _make_conn()
        rec = _run_hc(hc_cancelled_blocker_dependencies, conn)
        assert _result(rec).result == "PASS"

    def test_pass_blocker_not_cancelled(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, resolution) "
            "VALUES (500, 'Parent', 'implementing', NULL)"
        )
        conn.execute(
            "INSERT INTO item_dependencies "
            "(dependent_item, blocking_item, gate_point, satisfaction, "
            "source, rationale, evidence_json, created_at) "
            "VALUES ('YOK-600', 'YOK-500', 'activation', 'status:done', "
            "'test', '', '{}', '2026-01-01T00:00:00Z')"
        )
        rec = _run_hc(hc_cancelled_blocker_dependencies, conn)
        assert _result(rec).result == "PASS"

    def test_warn_cancelled_blocker_fixture_1270_1269(self):
        """Canonical shape: blocker cancelled,
        resolution=obsolete, no resolution_ref."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, resolution, resolution_ref) "
            "VALUES (1269, 'Cancelled blocker', 'cancelled', 'obsolete', NULL)"
        )
        conn.execute(
            "INSERT INTO items (id, title, status) "
            "VALUES (1270, 'Dependent', 'refined-idea')"
        )
        conn.execute(
            "INSERT INTO item_dependencies "
            "(dependent_item, blocking_item, gate_point, satisfaction, "
            "source, rationale, evidence_json, created_at) "
            "VALUES ('YOK-1270', 'YOK-1269', 'integration', 'fact:merged', "
            "'test', '', '{}', '2026-01-01T00:00:00Z')"
        )
        rec = _run_hc(hc_cancelled_blocker_dependencies, conn)
        res = _result(rec)
        assert res.result == "WARN"
        assert "YOK-1270 <- YOK-1269" in res.detail
        assert "gate=integration" in res.detail
        assert "satisfaction=fact:merged" in res.detail
        assert "resolution=obsolete" in res.detail

    def test_warn_cancelled_blocker_fixture_1210_1211(self):
        """Canonical shape from the spec."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, resolution, resolution_ref) "
            "VALUES (1211, 'Cancelled blocker', 'cancelled', 'obsolete', NULL)"
        )
        conn.execute(
            "INSERT INTO items (id, title, status) "
            "VALUES (1210, 'Dependent', 'refined-idea')"
        )
        conn.execute(
            "INSERT INTO item_dependencies "
            "(dependent_item, blocking_item, gate_point, satisfaction, "
            "source, rationale, evidence_json, created_at) "
            "VALUES ('YOK-1210', 'YOK-1211', 'integration', 'fact:merged', "
            "'test', '', '{}', '2026-01-01T00:00:00Z')"
        )
        rec = _run_hc(hc_cancelled_blocker_dependencies, conn)
        res = _result(rec)
        assert res.result == "WARN"
        assert "YOK-1210 <- YOK-1211" in res.detail

    def test_warn_lists_multiple_rows(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, resolution) "
            "VALUES (100, 'Cancelled A', 'cancelled', 'obsolete')"
        )
        conn.execute(
            "INSERT INTO items (id, title, status, resolution) "
            "VALUES (101, 'Cancelled B', 'cancelled', 'wontfix')"
        )
        for dep, blk in [("YOK-200", "YOK-100"), ("YOK-201", "YOK-101")]:
            p = _p(conn)
            conn.execute(
                "INSERT INTO item_dependencies "
                "(dependent_item, blocking_item, gate_point, satisfaction, "
                "source, rationale, evidence_json, created_at) "
                f"VALUES ({p}, {p}, 'activation', 'status:done', "
                "'test', '', '{}', '2026-01-01T00:00:00Z')",
                (dep, blk),
            )
        rec = _run_hc(hc_cancelled_blocker_dependencies, conn)
        res = _result(rec)
        assert res.result == "WARN"
        assert res.detail.count("\n") == 1  # two lines joined by one newline
        assert "YOK-200 <- YOK-100" in res.detail
        assert "YOK-201 <- YOK-101" in res.detail
