"""Tests for yoke_core.domain.epic — proceed_triage_and_handoff path.

Split from test_epic_cli.py: TestProceedTriageAndHandoff. Covers the
Python-owned PROCEED-path reviewed-handoff helper. Native simulation receipt
identity/readback is covered by the function adapter tests.
"""

from __future__ import annotations

from unittest.mock import patch


from runtime.api.conftest import insert_item
from yoke_core.domain import epic
from runtime.api.test_epic_cascade_dispatch import (  # noqa: F401
    db_with_chain,
)
from runtime.api.test_epic_tasks import db, db_with_task  # noqa: F401,F811


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

    def _seed_simulation_requirement(self, db, item_id: int = 42) -> int:  # noqa: F811
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
               (qa_requirement_id, performed_by, qa_kind, verdict, raw_result, created_at)
               VALUES (100, 'agent', 'simulation', 'fail',
                       '{"body":"SIMULATION: GAPS FOUND","phase":"integration"}',
                       '2026-01-01T00:00:00Z')"""
        )
        db.commit()
        return 100

    def test_proceed_success_records_triage_and_hands_off(self, db):  # noqa: F811
        """PROCEED path auto-advances parent and releases claim."""
        insert_item(db, id=42, status="reviewing-implementation")
        self._seed_simulation_requirement(db, 42)

        with (
            patch(
                "yoke_core.domain.epic.connect", return_value=self.NoCloseConnection(db)
            ),
            patch(
                "yoke_core.domain.qa_simulation_triage.record_simulation_triage",
                return_value={"event_id": "triage"},
            ) as run_add,
            patch(
                "yoke_core.domain.conduct_reviewed_handoff.run", return_value=0
            ) as handoff,
        ):
            rc = epic.proceed_triage_and_handoff(
                42,
                recommendation="PROCEED",
                gap_summary="1 WARNING gap",
                filed_item_ids=["YOK-99", "YOK-100"],
                session_id="sess-1",
            )

        assert rc == 0
        run_add.assert_called_once()
        call_kwargs = run_add.call_args[1]
        assert call_kwargs["recommendation"] == "PROCEED"
        assert call_kwargs["filed_public_refs"] == ["YOK-99", "YOK-100"]
        assert call_kwargs["rationale"] == "1 WARNING gap"
        # Handoff was called
        handoff.assert_called_once_with(42, session_id="sess-1")

    def test_proceed_missing_requirement_returns_1(self, db):  # noqa: F811
        """No simulation requirement → hard failure, no handoff attempted."""
        insert_item(db, id=42, status="reviewing-implementation")
        # No simulation requirement seeded

        with (
            patch(
                "yoke_core.domain.epic.connect", return_value=self.NoCloseConnection(db)
            ),
            patch("yoke_core.domain.conduct_reviewed_handoff.run") as handoff,
        ):
            rc = epic.proceed_triage_and_handoff(42, recommendation="PROCEED")

        assert rc == 1
        handoff.assert_not_called()

    def test_proceed_handoff_failure_returns_2(self, db):  # noqa: F811
        """Handoff failure → hard failure, no false success."""
        insert_item(db, id=42, status="reviewing-implementation")
        self._seed_simulation_requirement(db, 42)

        with (
            patch(
                "yoke_core.domain.epic.connect", return_value=self.NoCloseConnection(db)
            ),
            patch(
                "yoke_core.domain.qa_simulation_triage.record_simulation_triage",
                return_value={"event_id": "triage"},
            ),
            patch(
                "yoke_core.domain.conduct_reviewed_handoff.run", return_value=3
            ) as handoff,
        ):
            rc = epic.proceed_triage_and_handoff(
                42,
                recommendation="PROCEED",
                session_id="sess-1",
            )

        assert rc == 2
        handoff.assert_called_once_with(42, session_id="sess-1")

    def test_proceed_no_filed_items(self, db):  # noqa: F811
        """PROCEED with zero gaps to file still records triage and hands off."""
        insert_item(db, id=42, status="reviewing-implementation")
        self._seed_simulation_requirement(db, 42)

        with (
            patch(
                "yoke_core.domain.epic.connect", return_value=self.NoCloseConnection(db)
            ),
            patch(
                "yoke_core.domain.qa_simulation_triage.record_simulation_triage",
                return_value={"event_id": "triage"},
            ) as run_add,
            patch("yoke_core.domain.conduct_reviewed_handoff.run", return_value=0),
        ):
            rc = epic.proceed_triage_and_handoff(
                42,
                recommendation="PROCEED",
            )

        assert rc == 0
        call_kwargs = run_add.call_args[1]
        assert call_kwargs["filed_public_refs"] == []

    def test_proceed_rerun_after_success_is_idempotent_noop(self, db):  # noqa: F811
        """P-2: rerunning after a clean handoff no-ops without duplicate writes."""
        insert_item(db, id=42, status="reviewed-implementation")

        with (
            patch(
                "yoke_core.domain.epic.connect", return_value=self.NoCloseConnection(db)
            ),
            patch(
                "yoke_core.domain.qa_simulation_triage.record_simulation_triage",
                return_value={"event_id": "triage"},
            ) as run_add,
            patch("yoke_core.domain.conduct_reviewed_handoff.run") as handoff,
        ):
            rc = epic.proceed_triage_and_handoff(
                42,
                recommendation="PROCEED",
                filed_item_ids=["YOK-99"],
                session_id="sess-1",
            )

        assert rc == 0
        run_add.assert_not_called()
        handoff.assert_not_called()
