"""Doctor HC tests (Preview + shepherd + event HCs).

Other doctor_hc_db_full tests live in sibling files (test_doctor_hc_db_full*.py).

Schema scaffolding shared via _doctor_hc_db_full_test_helpers (private module).
"""

from __future__ import annotations

from unittest.mock import patch

from yoke_core.engines.doctor import (
    hc_event_callsite_registry_sync,
    hc_event_emission_rate,
    hc_event_registry_coverage,
    hc_preview_occupancy_stale,
    hc_shepherd_lifecycle,
)
from runtime.api.conftest import (
    insert_deployment_run,
    insert_event,
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.engines._doctor_hc_db_full_test_helpers import (
    _add_deployment_preview_environments_table,
    _add_ephemeral_environments_table,
    _default_args,
    _result,
    _run_hc,
)
from yoke_core.engines._project_identity_test_helpers import _seed_project


class TestHCPreviewOccupancyStaleFull:
    """Tests for HC-preview-occupancy-stale."""

    def _add_project(self, conn, project_id="externalwebapp"):
        _seed_project(conn, project_id)
        conn.commit()

    def _setup_preview_table(self, conn):
        _add_deployment_preview_environments_table(conn)

    def test_pass_active_claim(self, test_db):
        """Test 14: PASS when preview is actively claimed by executing run."""
        self._add_project(test_db)
        self._setup_preview_table(test_db)
        insert_deployment_run(test_db, id="run-active", project="externalwebapp",
                              flow="externalwebapp-release", status="executing",
                              started_at="2026-04-08T00:00:00Z")
        test_db.execute(
            "INSERT INTO deployment_preview_environments (project_id, env_name, run_id, status, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (2, "staging", "run-active", "claimed", "2026-01-01T00:00:00Z"),
        )
        test_db.commit()
        rec = _run_hc(hc_preview_occupancy_stale, test_db)
        assert _result(rec).result == "PASS"

    def test_warn_claimed_by_completed_run(self, test_db):
        """Test 15: WARN when preview claimed by completed run."""
        self._add_project(test_db)
        self._setup_preview_table(test_db)
        insert_deployment_run(test_db, id="run-done", project="externalwebapp",
                              flow="externalwebapp-release", status="succeeded",
                              completed_at="2026-04-08T00:00:00Z")
        test_db.execute(
            "INSERT INTO deployment_preview_environments (project_id, env_name, run_id, status, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (2, "staging", "run-done", "claimed", "2026-01-01T00:00:00Z"),
        )
        test_db.commit()
        rec = _run_hc(hc_preview_occupancy_stale, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "staging" in r.detail

    def test_warn_claimed_by_failed_run(self, test_db):
        """Test 16: WARN when preview claimed by failed run."""
        self._add_project(test_db)
        self._setup_preview_table(test_db)
        insert_deployment_run(test_db, id="run-fail", project="externalwebapp",
                              flow="externalwebapp-release", status="failed",
                              completed_at="2026-04-08T00:00:00Z")
        test_db.execute(
            "INSERT INTO deployment_preview_environments (project_id, env_name, run_id, status, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (2, "preview-qa", "run-fail", "claimed", "2026-01-01T00:00:00Z"),
        )
        test_db.commit()
        rec = _run_hc(hc_preview_occupancy_stale, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "preview-qa" in r.detail

    def test_available_previews_not_flagged(self, test_db):
        """Test 17: Available previews not flagged."""
        self._add_project(test_db)
        self._setup_preview_table(test_db)
        insert_deployment_run(test_db, id="run-x", project="externalwebapp",
                              flow="externalwebapp-release", status="succeeded",
                              completed_at="2026-04-08T00:00:00Z")
        test_db.execute(
            "INSERT INTO deployment_preview_environments (project_id, env_name, run_id, status, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (2, "staging", "run-x", "available", "2026-01-01T00:00:00Z"),
        )
        test_db.commit()
        rec = _run_hc(hc_preview_occupancy_stale, test_db)
        assert _result(rec).result == "PASS"


class TestHCShepherdLifecycleFull:
    """Tests for HC-shepherd-lifecycle: shepherd lifecycle enforcement."""

    def _insert_epic(self, conn, epic_id, status):
        insert_item(conn, id=epic_id, title=f"Test epic {epic_id}",
                    type="epic", status=status, spec="body")

    def _insert_verdict(self, conn, item_ref, transition, verdict):
        conn.execute(
            "INSERT INTO shepherd_verdicts (item, transition, worker, verdict, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (item_ref, transition, "PM", verdict, "2026-01-01T00:00:00Z"),
        )
        conn.commit()

    def test_pass_no_epics_past_refined_idea(self, test_db):
        """Test 1: PASS when no epics past refined-idea."""
        self._insert_epic(test_db, 10, "idea")
        self._insert_epic(test_db, 11, "refined-idea")
        rec = _run_hc(hc_shepherd_lifecycle, test_db)
        assert _result(rec).result == "PASS"

    def test_warn_planning_no_verdict(self, test_db):
        """Test 2: WARN for epic at planning without refined_idea_to_planning verdict."""
        self._insert_epic(test_db, 20, "planning")
        rec = _run_hc(hc_shepherd_lifecycle, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "YOK-20" in r.detail
        assert "refined_idea_to_planning" in r.detail

    def test_pass_planning_with_caveats_verdict(self, test_db):
        """Test 3: PASS for epic at planning with refined_idea_to_planning CAVEATS verdict."""
        self._insert_epic(test_db, 30, "planning")
        self._insert_verdict(test_db, "YOK-30", "refined_idea_to_planning", "CAVEATS")
        rec = _run_hc(hc_shepherd_lifecycle, test_db)
        assert "YOK-30" not in _result(rec).detail

    def test_non_epic_excluded(self, test_db):
        """Test 4: Non-epic items excluded."""
        insert_item(test_db, id=40, title="Non-epic implementing test",
                    type="issue", status="implementing", spec="body")
        rec = _run_hc(hc_shepherd_lifecycle, test_db)
        assert "YOK-40" not in _result(rec).detail

    def test_warn_plan_drafted_missing_verdict(self, test_db):
        """WARN for epic at plan-drafted missing planning_to_plan_drafted."""
        self._insert_epic(test_db, 45, "plan-drafted")
        self._insert_verdict(test_db, "YOK-45", "refined_idea_to_planning", "READY")
        rec = _run_hc(hc_shepherd_lifecycle, test_db)
        r = _result(rec)
        assert "YOK-45" in r.detail
        assert "planning_to_plan_drafted" in r.detail

    def test_warn_refining_plan_missing_verdict(self, test_db):
        """WARN for epic at refining-plan missing planning_to_plan_drafted."""
        self._insert_epic(test_db, 46, "refining-plan")
        self._insert_verdict(test_db, "YOK-46", "refined_idea_to_planning", "READY")
        rec = _run_hc(hc_shepherd_lifecycle, test_db)
        r = _result(rec)
        assert "YOK-46" in r.detail
        assert "planning_to_plan_drafted" in r.detail

    def test_warn_planned_missing_second_verdict(self, test_db):
        """Test 5: WARN for epic at planned missing planning_to_plan_drafted."""
        self._insert_epic(test_db, 50, "planned")
        self._insert_verdict(test_db, "YOK-50", "refined_idea_to_planning", "READY")
        rec = _run_hc(hc_shepherd_lifecycle, test_db)
        r = _result(rec)
        assert "YOK-50" in r.detail
        assert "planning_to_plan_drafted" in r.detail

    def test_implementing_missing_first_gate_no_double_report(self, test_db):
        """Test 6: Implementing epic missing first gate is not double-reported."""
        self._insert_epic(test_db, 60, "implementing")
        rec = _run_hc(hc_shepherd_lifecycle, test_db)
        r = _result(rec)
        assert "YOK-60" in r.detail
        assert "refined_idea_to_planning" in r.detail
        # Should NOT also report planning_to_plan_drafted since first gate is already missing
        assert r.detail.count("YOK-60") == 1

    def test_shepherd_lifecycle_warn_severity(self, test_db):
        """Test 7: HC-shepherd-lifecycle issues appear as WARN severity."""
        self._insert_epic(test_db, 70, "planning")
        rec = _run_hc(hc_shepherd_lifecycle, test_db)
        assert _result(rec).result == "WARN"

    def test_multiple_epics_mixed(self, test_db):
        """Test 8: Multiple epics with mixed verdict status."""
        self._insert_epic(test_db, 80, "planning")  # missing first verdict
        self._insert_epic(test_db, 81, "planned")   # has both verdicts
        self._insert_verdict(test_db, "YOK-81", "refined_idea_to_planning", "READY")
        self._insert_verdict(test_db, "YOK-81", "planning_to_plan_drafted", "CAVEATS")
        rec = _run_hc(hc_shepherd_lifecycle, test_db)
        r = _result(rec)
        assert "YOK-80" in r.detail
        assert "YOK-81" not in r.detail


# HC-event-registry-coverage, HC-event-emission-rate,
# HC-event-callsite-registry-sync tests (16 from shell)


class TestHCEventRegistryCoverage:
    """Tests for HC-event-registry-coverage."""

    def test_pass_no_registry_table(self, test_db):
        """PASS when event_registry table absent."""
        test_db.execute("DROP TABLE IF EXISTS event_registry")
        test_db.commit()
        rec = _run_hc(hc_event_registry_coverage, test_db)
        r = _result(rec)
        assert r.result == "PASS"
        assert "event_registry table not present" in r.detail

    def test_warn_stale_entries(self, test_db):
        """WARN on stale registry entries."""
        test_db.execute(
            "INSERT INTO event_registry (event_name, event_kind, event_type, owner_service, description, status) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            ("StaleEvent", "system", "generic", "cli", "test", "active"),
        )
        test_db.execute(
            "INSERT INTO event_registry (event_name, event_kind, event_type, owner_service, description, status) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            ("FreshEvent", "system", "generic", "cli", "test", "active"),
        )
        insert_event(test_db, event_id="evt-fresh-1", event_name="FreshEvent")
        rec = _run_hc(hc_event_registry_coverage, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "Stale registry entries" in r.detail
        assert "StaleEvent" in r.detail

    def test_pass_expected_low_cadence_active_without_recent_emission(self, test_db):
        """Expected low-cadence active entries do not warn solely for no emission."""
        test_db.execute(
            "INSERT INTO event_registry (event_name, event_kind, event_type, owner_service, description, status) VALUES (%s, %s, %s, %s, %s, %s)",
            ("BrowserDaemonStartupFailed", "system", "browser_daemon", "browser_qa", "rare failure path", "active"),
        )
        assert _result(_run_hc(hc_event_registry_coverage, test_db)).result == "PASS"

    def test_warn_rogue_events(self, test_db):
        """WARN on rogue events."""
        insert_event(test_db, event_id="evt-rogue-1", event_name="RogueEvent")
        rec = _run_hc(hc_event_registry_coverage, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "Rogue events" in r.detail
        assert "RogueEvent" in r.detail

    def test_pass_when_clean(self, test_db):
        """PASS when registry and emissions are clean."""
        test_db.execute(
            "INSERT INTO event_registry (event_name, event_kind, event_type, owner_service, description, status) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            ("GoodEvent", "system", "generic", "cli", "test", "active"),
        )
        insert_event(test_db, event_id="evt-good-1", event_name="GoodEvent")
        rec = _run_hc(hc_event_registry_coverage, test_db)
        assert _result(rec).result == "PASS"


class TestHCEventEmissionRate:
    """Tests for HC-event-emission-rate."""

    def test_pass_no_events_table(self, test_db):
        """PASS when events table absent."""
        test_db.execute("DROP TABLE IF EXISTS events")
        test_db.commit()
        rec = _run_hc(hc_event_emission_rate, test_db)
        r = _result(rec)
        assert r.result == "PASS"
        assert "events table not present" in r.detail

    def test_pass_no_sessions_in_24h(self, test_db):
        """PASS when no sessions in 24h."""
        rec = _run_hc(hc_event_emission_rate, test_db)
        r = _result(rec)
        assert r.result == "PASS"
        assert "No sessions in 24h" in r.detail

    def test_warn_zero_events_despite_sessions(self, test_db):
        """WARN when zero events despite active sessions."""
        test_db.execute(
            "INSERT INTO epic_dispatch_chains "
            "(epic_id, worktree, last_updated) VALUES (%s, %s, %s)",
            (431, "YOK-431", iso8601_now()),
        )
        test_db.commit()
        rec = _run_hc(hc_event_emission_rate, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "0 events emitted" in r.detail

    def test_pass_events_with_sessions(self, test_db):
        """PASS when events emitted with active sessions."""
        test_db.execute(
            "INSERT INTO epic_dispatch_chains "
            "(epic_id, worktree, last_updated) VALUES (%s, %s, %s)",
            (431, "YOK-431", iso8601_now()),
        )
        insert_event(test_db, event_id="evt-rate-1", event_name="SomeEvent")
        rec = _run_hc(hc_event_emission_rate, test_db)
        r = _result(rec)
        assert r.result == "PASS"
        assert "1 events emitted" in r.detail


class TestHCEventCallsiteRegistrySync:
    """Tests for HC-event-callsite-registry-sync."""

    def test_pass_no_registry_table(self, test_db):
        """PASS when event_registry table absent."""
        test_db.execute("DROP TABLE IF EXISTS event_registry")
        test_db.commit()
        rec = _run_hc(hc_event_callsite_registry_sync, test_db)
        r = _result(rec)
        assert r.result == "PASS"
        assert "event_registry table not present" in r.detail

    def test_pass_no_repo_root(self, test_db):
        """PASS when repo root cannot be resolved."""
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None):
            rec = _run_hc(hc_event_callsite_registry_sync, test_db)
        assert _result(rec).result == "PASS"
