"""Tests for the Python doctor engine (DB-only health checks): mid HCs.

Other HC tests live in test_doctor_db.py and test_doctor_db_hcs_b.py.
Exit-code tests live in test_doctor_db_exit.py.

Schema scaffolding shared via _doctor_db_test_helpers (private module).
"""

from __future__ import annotations

from yoke_core.engines.doctor import (
    RecordCollector,
    hc_epic_validation,
    hc_orphan_fk,
    hc_orphaned_runs,
    hc_preview_occupancy_stale,
    hc_run_item_status_consistency,
    hc_run_qa_unsatisfied,
    hc_stale_runs,
    hc_undeployed_done,
    hc_validation_no_qa_reqs,
)

from yoke_core.engines._doctor_db_test_helpers import (
    _default_args,
    _get_result,
    _iso_offset,
    _p,
    conn,
)


class TestHCEpicValidation:
    def test_pass_valid_epic(self, conn):
        conn.execute("INSERT INTO epic_tasks (epic_id, task_num, title, status) VALUES (1, 1, 'T1', 'planning')")
        conn.execute("INSERT INTO epic_tasks (epic_id, task_num, title, status) VALUES (1, 2, 'T2', 'planned')")
        rec = RecordCollector()
        hc_epic_validation(conn, _default_args(), rec)
        assert _get_result(rec, "HC-epic-validation").result == "PASS"

    def test_pass_empty(self, conn):
        rec = RecordCollector()
        hc_epic_validation(conn, _default_args(), rec)
        assert _get_result(rec, "HC-epic-validation").result == "PASS"

    def test_warn_invalid_task_status(self, conn):
        conn.execute("INSERT INTO epic_tasks (epic_id, task_num, title, status) VALUES (1, 1, 'T1', 'bogus')")
        rec = RecordCollector()
        hc_epic_validation(conn, _default_args(), rec)
        r = _get_result(rec, "HC-epic-validation")
        assert r.result == "WARN"
        assert "invalid status" in r.detail


class TestHCUndeployedDone:
    def test_pass_no_done(self, conn):
        rec = RecordCollector()
        hc_undeployed_done(conn, _default_args(), rec)
        assert _get_result(rec, "HC-undeployed-done").result == "PASS"

    def test_pass_done_with_deploy(self, conn):
        p = _p(conn)
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, deployed_to, updated_at) "
            f"VALUES (1, 'T', 'issue', 'done', 'low', 'production', {p})",
            (_iso_offset(days=-30),),
        )
        rec = RecordCollector()
        hc_undeployed_done(conn, _default_args(), rec)
        assert _get_result(rec, "HC-undeployed-done").result == "PASS"

    def test_warn_done_no_deploy_with_flow(self, conn):
        p = _p(conn)
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, project_id, updated_at) "
            f"VALUES (1, 'T', 'issue', 'done', 'low', 2, {p})",
            (_iso_offset(days=-14),),
        )
        conn.execute(
            "INSERT INTO deployment_flows (id, project_id, name, stages) "
            "VALUES ('f1', 2, 'main', '[]')"
        )
        rec = RecordCollector()
        hc_undeployed_done(conn, _default_args(), rec)
        r = _get_result(rec, "HC-undeployed-done")
        assert r.result == "WARN"
        assert "YOK-1" in r.detail


class TestHCOrphanFK:
    def test_pass_no_orphans(self, conn):
        rec = RecordCollector()
        hc_orphan_fk(conn, _default_args(), rec)
        r = _get_result(rec, "HC-orphan-fk")
        assert r.result == "PASS"
        assert "0 orphaned FK references" in r.detail

    def test_fail_orphaned_caveat(self, conn):
        conn.execute("INSERT INTO caveat_dispositions (id, verdict_id) VALUES (1, 999)")
        rec = RecordCollector()
        hc_orphan_fk(conn, _default_args(), rec)
        r = _get_result(rec, "HC-orphan-fk")
        assert r.result == "FAIL"
        assert "caveat_dispositions" in r.detail


class TestHCOrphanedRuns:
    def test_pass_all_runs_populated(self, conn):
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, created_at) "
            "VALUES ('r1', 1, 'succeeded', '2025-01-01T00:00:00')"
        )
        conn.execute("INSERT INTO deployment_run_items (run_id, item_id) VALUES ('r1', 1)")
        rec = RecordCollector()
        hc_orphaned_runs(conn, _default_args(), rec)
        assert _get_result(rec, "HC-orphaned-runs").result == "PASS"

    def test_warn_empty_run_never_started(self, conn):
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, created_at) "
            "VALUES ('r1', 1, 'created', '2025-01-01T00:00:00')"
        )
        rec = RecordCollector()
        hc_orphaned_runs(conn, _default_args(), rec)
        r = _get_result(rec, "HC-orphaned-runs")
        assert r.result == "WARN"
        assert "no member items" in r.detail

    def test_pass_itemless_executed_run(self, conn):
        # Item-less runs that executed are environment-level deploys.
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, created_at) "
            "VALUES ('r1', 1, 'succeeded', '2025-01-01T00:00:00')"
        )
        rec = RecordCollector()
        hc_orphaned_runs(conn, _default_args(), rec)
        assert _get_result(rec, "HC-orphaned-runs").result == "PASS"


class TestHCStaleRuns:
    def test_pass_no_stale(self, conn):
        p = _p(conn)
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, started_at) "
            f"VALUES ('r1', 1, 'executing', {p})",
            (_iso_offset(hours=-2),),
        )
        rec = RecordCollector()
        hc_stale_runs(conn, _default_args(), rec)
        assert _get_result(rec, "HC-stale-runs").result == "PASS"

    def test_warn_stale_run(self, conn):
        p = _p(conn)
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, started_at, current_stage) "
            f"VALUES ('r1', 1, 'executing', {p}, 'deploy')",
            (_iso_offset(hours=-48),),
        )
        rec = RecordCollector()
        hc_stale_runs(conn, _default_args(), rec)
        r = _get_result(rec, "HC-stale-runs")
        assert r.result == "WARN"
        assert "executing for >24h" in r.detail


class TestHCRunItemStatusConsistency:
    def test_pass_consistent(self, conn):
        rec = RecordCollector()
        hc_run_item_status_consistency(conn, _default_args(), rec)
        assert _get_result(rec, "HC-run-item-status-consistency").result == "PASS"

    def test_warn_release_not_in_run(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (1, 'T', 'issue', 'release', 'low')"
        )
        rec = RecordCollector()
        hc_run_item_status_consistency(conn, _default_args(), rec)
        r = _get_result(rec, "HC-run-item-status-consistency")
        assert r.result == "WARN"
        assert "status=release" in r.detail

    def test_warn_implemented_in_executing_run(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (2, 'T2', 'issue', 'implemented', 'low')"
        )
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status) "
            "VALUES ('run-implemented', 1, 'executing')"
        )
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id) VALUES ('run-implemented', 2)"
        )
        rec = RecordCollector()
        hc_run_item_status_consistency(conn, _default_args(), rec)
        r = _get_result(rec, "HC-run-item-status-consistency")
        assert r.result == "WARN"
        assert "status=implemented" in r.detail


class TestHCRunQAUnsatisfied:
    def test_pass_no_pending(self, conn):
        rec = RecordCollector()
        hc_run_qa_unsatisfied(conn, _default_args(), rec)
        assert _get_result(rec, "HC-run-qa-unsatisfied").result == "PASS"

    def test_warn_pending_blocking(self, conn):
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status) "
            "VALUES ('r1', 1, 'succeeded')"
        )
        conn.execute(
            "INSERT INTO deployment_run_qa (run_id, check_name, blocking, status) "
            "VALUES ('r1', 'smoke-test', 1, 'pending')"
        )
        rec = RecordCollector()
        hc_run_qa_unsatisfied(conn, _default_args(), rec)
        r = _get_result(rec, "HC-run-qa-unsatisfied")
        assert r.result == "WARN"
        assert "smoke-test" in r.detail


class TestHCPreviewOccupancyStale:
    def test_pass_no_stale(self, conn):
        rec = RecordCollector()
        hc_preview_occupancy_stale(conn, _default_args(), rec)
        assert _get_result(rec, "HC-preview-occupancy-stale").result == "PASS"

    def test_warn_stale_claim(self, conn):
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status) "
            "VALUES ('r1', 1, 'succeeded')"
        )
        conn.execute(
            "INSERT INTO deployment_preview_environments (project_id, env_name, run_id, status) "
            "VALUES (1, 'preview-1', 'r1', 'claimed')"
        )
        rec = RecordCollector()
        hc_preview_occupancy_stale(conn, _default_args(), rec)
        r = _get_result(rec, "HC-preview-occupancy-stale")
        assert r.result == "WARN"
        assert "should be released" in r.detail


class TestHCValidationNoQAReqs:
    def test_pass_has_qa(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (1, 'T', 'issue', 'reviewing-implementation', 'low')"
        )
        conn.execute(
            "INSERT INTO qa_requirements (item_id, qa_kind, qa_phase) "
            "VALUES (1, 'smoke', 'pre_merge')"
        )
        rec = RecordCollector()
        hc_validation_no_qa_reqs(conn, _default_args(), rec)
        assert _get_result(rec, "HC-validation-no-qa-reqs").result == "PASS"

    def test_warn_no_qa(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (1, 'T', 'issue', 'reviewing-implementation', 'low')"
        )
        rec = RecordCollector()
        hc_validation_no_qa_reqs(conn, _default_args(), rec)
        r = _get_result(rec, "HC-validation-no-qa-reqs")
        assert r.result == "WARN"
        assert "zero qa_requirements" in r.detail
