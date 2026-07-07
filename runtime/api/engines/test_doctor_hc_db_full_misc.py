"""Doctor HC tests for synthetic events and epic simulation.

Other doctor_hc_db_full tests live in sibling files (test_doctor_hc_db_full*.py).

Schema scaffolding shared via _doctor_hc_db_full_test_helpers (private module).
"""

from __future__ import annotations

from unittest.mock import patch

from yoke_core.engines.doctor import (
    hc_reviewed_implementation_epics_no_sim,
    hc_synthetic_event_contamination,
)
from runtime.api.conftest import (
    insert_deployment_run,
    insert_event,
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.engines._doctor_hc_db_full_test_helpers import (
    _default_args,
    _result,
    _run_hc,
)


class TestHCSyntheticEventContamination:
    """Tests for HC-synthetic-event-contamination."""

    def test_pass_no_events_table(self, test_db):
        """PASS when events table absent."""
        test_db.execute("DROP TABLE IF EXISTS events")
        test_db.commit()
        rec = _run_hc(hc_synthetic_event_contamination, test_db)
        r = _result(rec)
        assert r.result == "PASS"
        assert "events table not present" in r.detail

    def test_pass_empty_events_table(self, test_db):
        """PASS when the events table has no rows."""
        rec = _run_hc(hc_synthetic_event_contamination, test_db)
        r = _result(rec)
        assert r.result == "PASS"
        assert "empty" in r.detail

    def test_pass_clean_ledger_reports_sentinel_and_smoke_counts(self, test_db):
        """PASS when contamination is zero; still reports smoke + sentinel counts."""
        # Production row
        insert_event(
            test_db,
            event_id="evt-prod-1",
            session_id="claude-code-20260411T120000Z-00001",
            event_name="HarnessSessionStarted",
        )
        # Sentinel row (legitimate history)
        insert_event(
            test_db,
            event_id="evt-sentinel-1",
            session_id="migration-zero-legacy",
            event_name="TaskStatusChanged",
        )
        # Intentional smoke row (tagged)
        insert_event(
            test_db,
            event_id="evt-smoke-1",
            session_id="test-smoke-a",
            event_name="SmokeEmitted",
            anomaly_flags="synthetic_smoke",
        )
        rec = _run_hc(hc_synthetic_event_contamination, test_db)
        r = _result(rec)
        assert r.result == "PASS", r.detail
        assert "clean" in r.detail
        assert "synthetic_smoke" in r.detail
        assert "sentinel" in r.detail.lower()

    def test_warn_on_leaked_test_session_rows(self, test_db):
        """WARN when test-prefixed rows leak into the ledger without the smoke tag."""
        insert_event(
            test_db,
            event_id="evt-leak-1",
            session_id="test-leak-1",
            event_name="HarnessSessionStarted",
        )
        insert_event(
            test_db,
            event_id="evt-leak-2",
            session_id="sess-1",
            event_name="WorkClaimed",
        )
        insert_event(
            test_db,
            event_id="evt-leak-3",
            session_id="dup",
            event_name="WorkReleased",
        )
        rec = _run_hc(hc_synthetic_event_contamination, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "3 synthetic rows" in r.detail
        assert "HarnessSessionStarted" in r.detail
        assert "WorkClaimed" in r.detail
        assert "WorkReleased" in r.detail

    def test_warn_excludes_synthetic_smoke_tagged_rows(self, test_db):
        """Rows tagged with synthetic_smoke are excluded from contamination counts."""
        # One real leak
        insert_event(
            test_db,
            event_id="evt-real-leak",
            session_id="test-leak-x",
            event_name="HarnessSessionStarted",
        )
        # One intentional tagged row — must NOT be counted as contamination
        insert_event(
            test_db,
            event_id="evt-tagged",
            session_id="test-smoke-y",
            event_name="SmokeEmitted",
            anomaly_flags="synthetic_smoke",
        )
        rec = _run_hc(hc_synthetic_event_contamination, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "1 synthetic rows" in r.detail
        # smoke count line must report 1
        assert "Intentional smoke rows (tagged synthetic_smoke): 1" in r.detail

    def test_warn_excludes_sentinel_session_rows(self, test_db):
        """Sentinel session_ids are never counted as contamination."""
        for sid in ("unknown", "migration-zero-legacy", "status-events-backfill"):
            insert_event(
                test_db,
                event_id=f"evt-{sid}",
                session_id=sid,
                event_name="LegitimateHistoricalEvent",
            )
        rec = _run_hc(hc_synthetic_event_contamination, test_db)
        r = _result(rec)
        assert r.result == "PASS", r.detail
        assert "sentinel" in r.detail.lower()


class TestHCReviewedImplementationEpicsNoSimFull:
    """Tests for reviewed-implementation epics without integration simulation."""

    def test_pass_no_reviewed_epics(self, test_db):
        """Test 1: PASS when no epics in reviewed-implementation."""
        insert_item(test_db, id=10, title="Active epic test item", type="epic",
                    status="implementing")
        rec = _run_hc(hc_reviewed_implementation_epics_no_sim, test_db)
        assert _result(rec).result == "PASS"

    def test_pass_with_integration_simulation(self, test_db):
        """Test 2: PASS when reviewed epic has integration simulation."""
        insert_item(test_db, id=20, title="Reviewed epic with sim test", type="epic",
                    status="reviewed-implementation")
        # Use item_id as TEXT (matching the HC's CAST)
        req = insert_qa_requirement(test_db, item_id=20, qa_kind="simulation",
                                     qa_phase="verification",
                                     success_policy='{"type":"deterministic","phase":"integration"}')
        insert_qa_run(test_db, qa_requirement_id=req["id"],
                      executor_type="agent", qa_kind="simulation", verdict="pass")
        rec = _run_hc(hc_reviewed_implementation_epics_no_sim, test_db)
        assert _result(rec).result == "PASS"

    def test_fail_no_simulation(self, test_db):
        """Test 3: FAIL when reviewed epic has no simulation record."""
        insert_item(test_db, id=30, title="Reviewed epic no sim test item", type="epic",
                    status="reviewed-implementation")
        rec = _run_hc(hc_reviewed_implementation_epics_no_sim, test_db)
        r = _result(rec)
        assert r.result == "FAIL"
        assert "YOK-30" in r.detail

    def test_fail_plan_only_no_integration(self, test_db):
        """Test 4: FAIL when reviewed epic has plan sim but no integration sim."""
        insert_item(test_db, id=40, title="Reviewed epic plan only test", type="epic",
                    status="reviewed-implementation")
        req = insert_qa_requirement(test_db, item_id=40, qa_kind="simulation",
                                     qa_phase="verification",
                                     success_policy='{"type":"deterministic","phase":"plan"}')
        insert_qa_run(test_db, qa_requirement_id=req["id"],
                      executor_type="agent", qa_kind="simulation", verdict="pass")
        rec = _run_hc(hc_reviewed_implementation_epics_no_sim, test_db)
        r = _result(rec)
        assert r.result == "FAIL"
        assert "YOK-40" in r.detail

    def test_fail_multiple_all_listed(self, test_db):
        """Test 5: FAIL with multiple reviewed epics without simulation."""
        for eid in (50, 51, 52):
            insert_item(test_db, id=eid, title=f"Reviewed epic {eid} test",
                        type="epic", status="reviewed-implementation")
        rec = _run_hc(hc_reviewed_implementation_epics_no_sim, test_db)
        r = _result(rec)
        assert r.result == "FAIL"
        assert "YOK-50" in r.detail
        assert "YOK-51" in r.detail
        assert "YOK-52" in r.detail

    def test_pass_other_statuses_not_flagged(self, test_db):
        """Test 6: PASS when epics in other statuses lack simulation."""
        insert_item(test_db, id=60, title="Active epic no sim test", type="epic",
                    status="implementing")
        insert_item(test_db, id=61, title="Done epic no sim test", type="epic",
                    status="done")
        insert_item(test_db, id=62, title="Planned epic no sim test", type="epic",
                    status="planned")
        insert_item(test_db, id=63, title="Idea epic no sim test", type="epic",
                    status="idea")
        rec = _run_hc(hc_reviewed_implementation_epics_no_sim, test_db)
        assert _result(rec).result == "PASS"

    def test_idempotent(self, test_db):
        """Test 7: Idempotent check (same output on consecutive runs)."""
        insert_item(test_db, id=70, title="Reviewed epic idem test", type="epic",
                    status="reviewed-implementation")
        rec1 = _run_hc(hc_reviewed_implementation_epics_no_sim, test_db)
        rec2 = _run_hc(hc_reviewed_implementation_epics_no_sim, test_db)
        assert _result(rec1).result == _result(rec2).result
        assert _result(rec1).detail == _result(rec2).detail

    def test_performance_many_items(self, test_db):
        """Test 8: Performance check (runs quickly with many items)."""
        import time
        for i in range(1, 21):
            insert_item(test_db, id=i, title=f"Epic {i} perf test item",
                        type="epic", status="reviewed-implementation")
            if i % 2 == 0:
                req = insert_qa_requirement(
                    test_db, item_id=i, qa_kind="simulation",
                    qa_phase="verification",
                    success_policy='{"type":"deterministic","phase":"integration"}',
                )
                insert_qa_run(
                    test_db, qa_requirement_id=req["id"],
                    executor_type="agent", qa_kind="simulation", verdict="pass",
                )
        start = time.monotonic()
        _run_hc(hc_reviewed_implementation_epics_no_sim, test_db)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"HC took {elapsed:.1f}s, expected < 2s"
