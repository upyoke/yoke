"""Tests for HC-status-consistency.

Split from test_doctor_db.py to keep that file under the file-line cap.
Schema scaffolding shared via _doctor_db_test_helpers (private module).
"""

from __future__ import annotations

# Shared fixture functions intentionally remain module globals for pytest.
# ruff: noqa: F401, F811

from yoke_core.engines.doctor import (
    RecordCollector,
    hc_status_consistency,
)

from yoke_core.engines._doctor_db_test_helpers import (
    _default_args,
    _get_result,
    conn,
)
from runtime.api.api_workflow_test_helpers import (
    install_workflow_registry_and_pin_items,
)


class TestHCStatusConsistency:
    def test_pass_no_epics(self, conn):
        conn.execute("INSERT INTO items (id, title, workflow_id, workflow_version_id, status, priority) VALUES (1, 'T', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea', 'low')")
        install_workflow_registry_and_pin_items(conn)
        rec = RecordCollector()
        hc_status_consistency(conn, _default_args(), rec)
        r = _get_result(rec, "HC-status-consistency")
        assert r.result == "PASS"

    def test_fail_epic_no_tasks(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, priority) "
            "VALUES (10, 'E', 'epic', (SELECT current_version_id FROM workflows WHERE id='epic'), 'implementing', 'high')"
        )
        install_workflow_registry_and_pin_items(
            conn,
            workflow_id_by_item={10: "epic"},
        )
        rec = RecordCollector()
        hc_status_consistency(conn, _default_args(), rec)
        r = _get_result(rec, "HC-status-consistency")
        assert r.result == "FAIL"
        assert "no tasks in DB" in r.detail

    def test_pass_epic_with_tasks(self, conn):
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, priority) "
            "VALUES (10, 'E', 'epic', (SELECT current_version_id FROM workflows WHERE id='epic'), 'implementing', 'high')"
        )
        install_workflow_registry_and_pin_items(
            conn,
            workflow_id_by_item={10: "epic"},
        )
        conn.execute("INSERT INTO epic_tasks (epic_id, task_num, title, status) VALUES (10, 1, 'T1', 'planning')")
        rec = RecordCollector()
        hc_status_consistency(conn, _default_args(), rec)
        r = _get_result(rec, "HC-status-consistency")
        assert r.result == "PASS"

    def test_pass_refined_idea_epic_without_tasks(self, conn):
        # Epic decomposition runs in /yoke shepherd (refined-idea -> planning),
        # so refined-idea epics legitimately have no epic_tasks rows yet.
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, priority) "
            "VALUES (11, 'E', 'epic', (SELECT current_version_id FROM workflows WHERE id='epic'), 'refined-idea', 'high')"
        )
        install_workflow_registry_and_pin_items(
            conn,
            workflow_id_by_item={11: "epic"},
        )
        rec = RecordCollector()
        hc_status_consistency(conn, _default_args(), rec)
        r = _get_result(rec, "HC-status-consistency")
        assert r.result == "PASS"

    def test_fail_planning_epic_without_tasks(self, conn):
        # planning-status epics MUST have tasks (architect populates them).
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, priority) "
            "VALUES (12, 'E', 'epic', (SELECT current_version_id FROM workflows WHERE id='epic'), 'planning', 'high')"
        )
        install_workflow_registry_and_pin_items(
            conn,
            workflow_id_by_item={12: "epic"},
        )
        rec = RecordCollector()
        hc_status_consistency(conn, _default_args(), rec)
        r = _get_result(rec, "HC-status-consistency")
        assert r.result == "FAIL"
        assert "no tasks in DB" in r.detail
