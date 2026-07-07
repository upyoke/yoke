"""Tests for yoke_core.domain.epic — proceed_triage_and_handoff path.

Split from test_epic_cli.py: TestProceedTriageAndHandoff. Covers the
Python-owned PROCEED-path reviewed-handoff helper plus the persist-and-verify
clean/gaps interactions.
"""

from __future__ import annotations

from unittest import mock
from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_item
from yoke_core.domain import epic
from runtime.api.test_epic_cascade_dispatch import db_with_chain  # noqa: F401
from runtime.api.test_epic_tasks import db, db_with_task  # noqa: F401


class TestProceedTriageAndHandoff:
    """Python-owned PROCEED-path reviewed-handoff."""

    class NoCloseConnection:
        def __init__(self, conn):
            self._conn = conn

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def __enter__(self):
            return self._conn

        def __exit__(self, *args):
            return False

        def close(self):
            pass

    def _seed_simulation_requirement(self, db, item_id: int = 42) -> int:
        """Insert a simulation requirement with a GAPS FOUND run (mimics persist_and_verify)."""
        p = epic._placeholder(db)
        db.execute(
            f"""INSERT INTO qa_requirements
               (id, item_id, qa_kind, qa_phase, blocking_mode, requirement_source, success_policy, created_at)
               VALUES (100, {p}, 'simulation', 'verification', 'blocking',
                       'explicit', {p}, '2026-01-01T00:00:00Z')""",
            (
                str(item_id),
                '{"type":"deterministic","criteria":"result_pass","phase":"integration"}',
            ),
        )
        db.execute(
            """INSERT INTO qa_runs
               (qa_requirement_id, executor_type, qa_kind, verdict, raw_result, created_at)
               VALUES (100, 'agent', 'simulation', 'fail',
                       '{"body":"SIMULATION: GAPS FOUND","phase":"integration"}',
                       '2026-01-01T00:00:00Z')"""
        )
        db.commit()
        return 100

    def test_proceed_success_records_triage_and_hands_off(self, db):
        """AC-1/AC-2: PROCEED path auto-advances parent and releases claim."""
        insert_item(db, id=42, status="reviewing-implementation")
        self._seed_simulation_requirement(db, 42)

        with patch("yoke_core.domain.epic.connect", return_value=self.NoCloseConnection(db)), \
             patch("yoke_core.domain.epic._qa_run_add_silent") as run_add, \
             patch("yoke_core.domain.conduct_reviewed_handoff.run", return_value=0) as handoff:
            rc = epic.proceed_triage_and_handoff(
                42,
                recommendation="PROCEED",
                gap_summary="1 WARNING gap",
                filed_ticket_ids=["YOK-99", "YOK-100"],
                session_id="sess-1",
            )

        assert rc == 0
        # Triage run was recorded
        run_add.assert_called_once()
        call_kwargs = run_add.call_args[1]
        assert call_kwargs["verdict"] == "pass"
        assert call_kwargs["qa_kind"] == "simulation"
        assert "PROCEED" in call_kwargs["raw_result"]
        assert "YOK-99, YOK-100" in call_kwargs["raw_result"]
        # Handoff was called
        handoff.assert_called_once_with(42, session_id="sess-1")

    def test_proceed_missing_requirement_returns_1(self, db):
        """AC-6: No simulation requirement → hard failure, no handoff attempted."""
        insert_item(db, id=42, status="reviewing-implementation")
        # No simulation requirement seeded

        with patch("yoke_core.domain.epic.connect", return_value=self.NoCloseConnection(db)), \
             patch("yoke_core.domain.conduct_reviewed_handoff.run") as handoff:
            rc = epic.proceed_triage_and_handoff(42, recommendation="PROCEED")

        assert rc == 1
        handoff.assert_not_called()

    def test_proceed_handoff_failure_returns_2(self, db):
        """AC-6: Handoff failure → hard failure, no false success."""
        insert_item(db, id=42, status="reviewing-implementation")
        self._seed_simulation_requirement(db, 42)

        with patch("yoke_core.domain.epic.connect", return_value=self.NoCloseConnection(db)), \
             patch("yoke_core.domain.epic._qa_run_add_silent"), \
             patch("yoke_core.domain.conduct_reviewed_handoff.run", return_value=3) as handoff:
            rc = epic.proceed_triage_and_handoff(
                42, recommendation="PROCEED", session_id="sess-1",
            )

        assert rc == 2
        handoff.assert_called_once_with(42, session_id="sess-1")

    def test_proceed_no_filed_tickets(self, db):
        """PROCEED with zero gaps to file still records triage and hands off."""
        insert_item(db, id=42, status="reviewing-implementation")
        self._seed_simulation_requirement(db, 42)

        with patch("yoke_core.domain.epic.connect", return_value=self.NoCloseConnection(db)), \
             patch("yoke_core.domain.epic._qa_run_add_silent") as run_add, \
             patch("yoke_core.domain.conduct_reviewed_handoff.run", return_value=0):
            rc = epic.proceed_triage_and_handoff(
                42, recommendation="PROCEED",
            )

        assert rc == 0
        call_kwargs = run_add.call_args[1]
        assert '"none"' in call_kwargs["raw_result"]

    def test_proceed_rerun_after_success_is_idempotent_noop(self, db):
        """P-2: rerunning after a clean handoff no-ops without duplicate writes."""
        insert_item(db, id=42, status="reviewed-implementation")

        with patch("yoke_core.domain.epic.connect", return_value=self.NoCloseConnection(db)), \
             patch("yoke_core.domain.epic._qa_run_add_silent") as run_add, \
             patch("yoke_core.domain.conduct_reviewed_handoff.run") as handoff:
            rc = epic.proceed_triage_and_handoff(
                42,
                recommendation="PROCEED",
                filed_ticket_ids=["YOK-99"],
                session_id="sess-1",
            )

        assert rc == 0
        run_add.assert_not_called()
        handoff.assert_not_called()

    def test_clean_path_unchanged_no_proceed_helper(self):
        """AC-3: persist_and_verify CLEAN path still uses auto-handoff, not proceed helper."""
        from yoke_core.domain import persist_simulation

        sim_output = "SIMULATION: CLEAN\nEPIC: YOK-42"
        conn = mock.MagicMock()
        conn.__enter__ = mock.MagicMock(return_value=conn)
        conn.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch.object(persist_simulation, "connect", return_value=conn), \
             mock.patch.object(
                 persist_simulation._epic_domain, "simulation_upsert"
             ), \
             mock.patch.object(
                 persist_simulation._epic_domain, "simulation_get",
                 return_value="1|42|integration|CLEAN|body|2026-04-09",
             ), \
             mock.patch(
                 "yoke_core.domain.conduct_reviewed_handoff.run", return_value=0
             ) as handoff, \
             mock.patch.object(epic, "proceed_triage_and_handoff") as proceed:
            verdict = persist_simulation.persist_and_verify("42", "integration", sim_output)

        assert verdict == "CLEAN"
        # CLEAN uses direct handoff, not proceed helper
        handoff.assert_called_once_with(42)
        proceed.assert_not_called()

    def test_gaps_found_persist_does_not_handoff(self):
        """AC-3: plain GAPS FOUND persistence does not trigger any handoff."""
        from yoke_core.domain import persist_simulation

        sim_output = "SIMULATION: GAPS FOUND\nEPIC: YOK-42\n- Gap 1"
        conn = mock.MagicMock()
        conn.__enter__ = mock.MagicMock(return_value=conn)
        conn.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch.object(persist_simulation, "connect", return_value=conn), \
             mock.patch.object(
                 persist_simulation._epic_domain, "simulation_upsert"
             ), \
             mock.patch.object(
                 persist_simulation._epic_domain, "simulation_get",
                 return_value="1|42|integration|GAPS FOUND|body|2026-04-09",
             ), \
             mock.patch(
                 "yoke_core.domain.conduct_reviewed_handoff.run"
             ) as handoff, \
             mock.patch.object(epic, "proceed_triage_and_handoff") as proceed:
            verdict = persist_simulation.persist_and_verify("42", "integration", sim_output)

        assert verdict == "GAPS FOUND"
        handoff.assert_not_called()
        proceed.assert_not_called()
