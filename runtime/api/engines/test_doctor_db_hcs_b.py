"""Tests for the Python doctor engine (DB-only health checks): late HCs.

Other HC tests live in test_doctor_db.py and test_doctor_db_hcs_a.py.
Exit-code tests live in test_doctor_db_exit.py.

Schema scaffolding shared via _doctor_db_test_helpers (private module).
"""

from __future__ import annotations

from yoke_core.engines.doctor import (
    HEALTH_CHECKS,
    HealthCheck,
    RecordCollector,
    hc_deferred_items,
    hc_lifecycle_continuity,
    hc_orphaned_done_items,
    hc_orphaned_ephemeral,
    hc_shepherd_lifecycle,
    hc_smoke_artifact_orphan,
    hc_smoke_failure_stale,
)

from yoke_core.engines._doctor_db_test_helpers import (
    _default_args,
    _get_result,
    _iso_offset,
    conn,
)


class TestHCSmokeFailureStale:
    def test_pass_no_stale(self, conn):
        rec = RecordCollector()
        hc_smoke_failure_stale(conn, _default_args(), rec)
        assert _get_result(rec, "HC-smoke-failure-stale").result == "PASS"


class TestHCSmokeArtifactOrphan:
    def test_pass_no_orphans(self, conn):
        rec = RecordCollector()
        hc_smoke_artifact_orphan(conn, _default_args(), rec)
        assert _get_result(rec, "HC-smoke-artifact-orphan").result == "PASS"

    def test_warn_orphaned_artifact(self, conn):
        conn.execute(
            "INSERT INTO qa_artifacts (qa_run_id, artifact_type, path) "
            "VALUES (999, 'screenshot', '/tmp/s.png')"
        )
        rec = RecordCollector()
        hc_smoke_artifact_orphan(conn, _default_args(), rec)
        r = _get_result(rec, "HC-smoke-artifact-orphan")
        assert r.result == "WARN"
        assert "orphaned reference chain" in r.detail


class TestHCOrphanedDoneItems:
    def test_pass_clean(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (1, 'T', 'issue', 'done', 'low')"
        )
        rec = RecordCollector()
        hc_orphaned_done_items(conn, _default_args(), rec)
        assert _get_result(rec, "HC-orphaned-done-items").result == "PASS"

    def test_warn_worktree_set(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, worktree) "
            "VALUES (1, 'T', 'issue', 'done', 'low', 'YOK-1')"
        )
        rec = RecordCollector()
        hc_orphaned_done_items(conn, _default_args(), rec)
        r = _get_result(rec, "HC-orphaned-done-items")
        assert r.result == "WARN"
        assert "ceremony may have been bypassed" in r.detail


class TestHCDeferredItems:
    def test_pass_no_deferred(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, spec) "
            "VALUES (1, 'E', 'epic', 'done', 'high', 'All done.')"
        )
        rec = RecordCollector()
        hc_deferred_items(conn, _default_args(), rec)
        assert _get_result(rec, "HC-deferred-items").result == "PASS"

    def test_warn_unfiled(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, spec) "
            "VALUES (1, 'E', 'epic', 'done', 'high', "
            "'## Deferred Items\n- UNFILED: something to do\n## Done')"
        )
        rec = RecordCollector()
        hc_deferred_items(conn, _default_args(), rec)
        r = _get_result(rec, "HC-deferred-items")
        assert r.result == "WARN"
        assert "UNFILED" in r.detail

    def test_warn_deferral_language(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, spec) "
            "VALUES (1, 'E', 'epic', 'done', 'high', "
            "'Some feature was deferred to a follow-up without a ticket.')"
        )
        rec = RecordCollector()
        hc_deferred_items(conn, _default_args(), rec)
        r = _get_result(rec, "HC-deferred-items")
        assert r.result == "WARN"
        assert "deferral language" in r.detail


class TestHCShepherdLifecycle:
    def test_pass_verdicts_present(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (1, 'E', 'epic', 'implementing', 'high')"
        )
        conn.execute(
            "INSERT INTO shepherd_verdicts (item, transition, verdict) "
            "VALUES ('YOK-1', 'refined_idea_to_planning', 'READY')"
        )
        conn.execute(
            "INSERT INTO shepherd_verdicts (item, transition, verdict) "
            "VALUES ('YOK-1', 'planning_to_plan_drafted', 'READY')"
        )
        rec = RecordCollector()
        hc_shepherd_lifecycle(conn, _default_args(), rec)
        assert _get_result(rec, "HC-shepherd-lifecycle").result == "PASS"

    def test_warn_missing_verdict(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (1, 'E', 'epic', 'implementing', 'high')"
        )
        rec = RecordCollector()
        hc_shepherd_lifecycle(conn, _default_args(), rec)
        r = _get_result(rec, "HC-shepherd-lifecycle")
        assert r.result == "WARN"
        assert "refined_idea_to_planning" in r.detail


class TestHCLifecycleContinuity:
    def test_pass_transition_row_exists(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (1, 'T', 'issue', 'implementing', 'low')"
        )
        conn.execute(
            "INSERT INTO item_status_transitions (item_id, to_status) "
            "VALUES (1, 'implementing')"
        )
        rec = RecordCollector()
        hc_lifecycle_continuity(conn, _default_args(), rec)
        assert _get_result(rec, "HC-lifecycle-continuity").result == "PASS"

    def test_task_row_does_not_satisfy_item_continuity(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (1, 'T', 'issue', 'implementing', 'low')"
        )
        # A task-level transition (task_num set) is not the item's own.
        conn.execute(
            "INSERT INTO item_status_transitions (item_id, task_num, to_status) "
            "VALUES (1, 2, 'implementing')"
        )
        rec = RecordCollector()
        hc_lifecycle_continuity(conn, _default_args(), rec)
        assert _get_result(rec, "HC-lifecycle-continuity").result == "WARN"

    def test_warn_missing_transition_row(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (1, 'T', 'issue', 'implementing', 'low')"
        )
        rec = RecordCollector()
        hc_lifecycle_continuity(conn, _default_args(), rec)
        r = _get_result(rec, "HC-lifecycle-continuity")
        assert r.result == "WARN"
        assert "no matching item_status_transitions row" in r.detail


class TestHCOrphanedEphemeral:
    def test_pass_no_orphans(self, conn):
        rec = RecordCollector()
        hc_orphaned_ephemeral(conn, _default_args(), rec)
        assert _get_result(rec, "HC-orphaned-ephemeral").result == "PASS"

    def test_warn_active_env_for_done_item(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority) "
            "VALUES (1, 'T', 'issue', 'done', 'low')"
        )
        conn.execute(
            "INSERT INTO ephemeral_environments (item, status) "
            "VALUES ('YOK-1', 'running')"
        )
        rec = RecordCollector()
        hc_orphaned_ephemeral(conn, _default_args(), rec)
        r = _get_result(rec, "HC-orphaned-ephemeral")
        assert r.result == "WARN"
        assert "expected stopped" in r.detail


class TestHCRegistry:
    def test_all_hcs_registered(self):
        slugs = {hc.slug for hc in HEALTH_CHECKS}
        expected = {
            "status-consistency", "blocked-items", "dispatch-chain",
            "backlog-hygiene", "frontmatter-schema", "title-length",
            "epic-validation", "undeployed-done", "orphan-fk",
            "orphaned-runs", "stale-runs", "run-item-status-consistency",
            "run-qa-unsatisfied", "preview-occupancy-stale",
            "validation-no-qa-reqs", "smoke-failure-stale",
            "smoke-artifact-orphan", "orphaned-done-items",
            "deferred-items", "shepherd-lifecycle",
            "lifecycle-continuity", "orphaned-ephemeral",
        }
        assert expected.issubset(slugs)
