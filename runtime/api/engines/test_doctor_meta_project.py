"""Doctor meta-HCs covering project FK/JSON, flows, ephemeral envs, lifecycle.

Registry/quality/integrity/flow HCs live in test_doctor_meta.py.
Epic-task/body/dependency/flow HCs live in test_doctor_meta_lifecycle.py.

Schema scaffolding is shared via _doctor_meta_test_helpers (private module).
"""

from __future__ import annotations

from yoke_core.engines._doctor_meta_test_helpers import (
    _args,
    _insert_deployment_flow,
    _insert_item,
    _iso_offset,
    _make_conn,
    _p,
    _project_id,
    _results,
    _seed_project,
)
from yoke_core.engines.doctor import (
    RecordCollector,
    hc_duplicate_projects,
    hc_event_emission_rate,
    hc_event_registry_coverage,
    hc_null_project_items,
    hc_premature_done,
    hc_project_fk_integrity,
    hc_project_json_validity,
    hc_projects_without_flows,
    hc_reviewed_implementation_epics_no_sim,
    hc_zombie_ephemeral_envs,
)


class TestProjectFkIntegrity:
    def test_pass_valid_project(self):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, 1)
        rec = RecordCollector()
        hc_project_fk_integrity(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-project-fk-integrity"][0] == "PASS"

    def test_fail_invalid_project(self):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, 1, project="nonexistent")
        rec = RecordCollector()
        hc_project_fk_integrity(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-project-fk-integrity"][0] == "FAIL"


class TestProjectJsonValidity:
    def test_pass_when_table_exists(self):
        """Retired project-context JSON columns moved into the
        ``context_routing`` Project Structure family, where payloads are
        validated structurally on every write. The HC is now a no-op PASS
        when the projects table exists."""
        conn = _make_conn()
        _seed_project(conn, "yoke")
        rec = RecordCollector()
        hc_project_json_validity(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-project-json-validity"][0] == "PASS"


class TestProjectsWithoutFlows:
    def test_pass_project_has_flow(self):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_deployment_flow(conn, "f1")
        _insert_deployment_flow(conn, "buzz-flow", project="buzz")
        rec = RecordCollector()
        hc_projects_without_flows(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-projects-without-flows"][0] == "PASS"

    def test_warn_no_flows(self):
        conn = _make_conn()
        _seed_project(conn, "orphan")
        rec = RecordCollector()
        hc_projects_without_flows(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-projects-without-flows"][0] == "WARN"


class TestDuplicateProjects:
    def test_pass_unique(self):
        conn = _make_conn()
        _seed_project(conn, "a", "A", "/a")
        _seed_project(conn, "b", "B", "/b")
        rec = RecordCollector()
        hc_duplicate_projects(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-duplicate-projects"][0] == "PASS"

    def test_shared_checkout_paths_are_not_project_identity(self):
        conn = _make_conn()
        _seed_project(conn, "a", "A", "/same")
        _seed_project(conn, "b", "B", "/same")
        rec = RecordCollector()
        hc_duplicate_projects(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-duplicate-projects"][0] == "PASS"

    def test_warn_duplicate_public_item_prefix(self):
        conn = _make_conn()
        _seed_project(conn, "a", "A", "/a", public_item_prefix="TST")
        _seed_project(conn, "b", "B", "/b", public_item_prefix="TST")
        rec = RecordCollector()
        hc_duplicate_projects(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-duplicate-projects"][0] == "WARN"
        assert "public_item_prefix 'TST'" in res["HC-duplicate-projects"][1]


class TestNullProjectItems:
    def test_pass_all_have_project(self):
        conn = _make_conn()
        _insert_item(conn, 1, status="idea")
        rec = RecordCollector()
        hc_null_project_items(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-null-project-items"][0] == "PASS"

    def test_fail_null_project(self):
        conn = _make_conn()
        _insert_item(conn, 1, project=None, status="idea")
        rec = RecordCollector()
        hc_null_project_items(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-null-project-items"][0] == "FAIL"


class TestZombieEphemeralEnvs:
    def test_pass_no_zombies(self):
        conn = _make_conn()
        rec = RecordCollector()
        hc_zombie_ephemeral_envs(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-zombie-ephemeral-envs"][0] == "PASS"

    def test_warn_zombie_env(self):
        conn = _make_conn()
        p = _p(conn)
        conn.execute(
            "INSERT INTO ephemeral_environments "
            "(id, project_id, branch, status, created_at) "
            f"VALUES (1, {_project_id('buzz')}, 'feature', 'running', {p})",
            (_iso_offset(hours=-5),),
        )
        rec = RecordCollector()
        hc_zombie_ephemeral_envs(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-zombie-ephemeral-envs"][0] == "WARN"


class TestPrematureDone:
    def test_pass_done_with_merged_at(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status, merged_at) "
            "VALUES (1, 'Test', 'issue', 'done', '2026-01-01T00:00:00Z')"
        )
        rec = RecordCollector()
        hc_premature_done(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-premature-done"][0] == "PASS"

    def test_warn_done_without_merged(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status, merged_at) "
            "VALUES (1, 'Test', 'issue', 'done', NULL)"
        )
        rec = RecordCollector()
        hc_premature_done(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-premature-done"][0] == "WARN"


class TestPassedEpicsNoSim:
    def test_pass_when_no_passed_epics(self):
        conn = _make_conn()
        rec = RecordCollector()
        hc_reviewed_implementation_epics_no_sim(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-reviewed-implementation-epics-no-sim"][0] == "PASS"


class TestEventRegistryCoverage:
    def test_pass_no_registry(self):
        """When event_registry table is empty, should still PASS."""
        conn = _make_conn()
        rec = RecordCollector()
        hc_event_registry_coverage(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-event-registry-coverage"][0] in ("PASS", "WARN")


class TestEventEmissionRate:
    def test_pass_no_sessions(self):
        conn = _make_conn()
        rec = RecordCollector()
        hc_event_emission_rate(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-event-emission-rate"][0] == "PASS"
