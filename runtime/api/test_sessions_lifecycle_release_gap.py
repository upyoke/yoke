"""Task 004 — release-precondition test spine."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from yoke_core.domain.sessions_handler_outcome import (
    OUTCOME_BLOCKED, OUTCOME_COMPLETED, OUTCOME_INTERACTIVE_CHECKPOINT,
)
from yoke_core.domain.sessions_lifecycle_release import (
    release_work_claim_for_execution,
)
from yoke_core.domain.sessions_lifecycle_release_precondition import (
    REFUSAL_NON_TERMINAL_RELEASE,
    ReleasePreconditionResult,
    evaluate_release_precondition,
)
from yoke_core.domain.sessions_queries_chain import update_chain_checkpoint
from yoke_core.domain.work_claim_targets import (
    make_epic_task_target, make_item_target,
)
from runtime.api.fixtures import pg_testdb
from runtime.api.scheduler_test_fixtures import (
    EVENTS_SCHEMA, HARNESS_SESSIONS_SCHEMA, WORK_CLAIMS_SCHEMA,
)
from runtime.api.sessions_api_stale_test_helpers import apply_ddl_statements
from yoke_core.api.service_client_work_claims import (
    RELEASE_EXIT_ALREADY_TERMINAL,
    RELEASE_EXIT_PRECONDITION_REFUSED,
    _RELEASE_FAILURE_TO_EXIT,
)
from runtime.api.test_dependency_schema import (
    ITEMS_SCHEMA, ITEM_DEPENDENCIES_SCHEMA, PROJECTS_SCHEMA,
)
from runtime.api.test_constants import TEST_MODEL_ID


SESSION_ID = "019e1f0d-7f82-72d2-85ee-b46947b2a6fd"
ITEM_ID = 9999
EPIC_ID = 9998
_TS = "2026-05-13T01:58:26+00:00"


def _make_db():
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    for ddl in (PROJECTS_SCHEMA, ITEMS_SCHEMA, ITEM_DEPENDENCIES_SCHEMA,
                HARNESS_SESSIONS_SCHEMA, WORK_CLAIMS_SCHEMA, EVENTS_SCHEMA):
        apply_ddl_statements(conn, ddl)
    conn.commit()
    return conn


def _seed_session(conn) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model,"
        " execution_lane, capabilities, workspace, mode, offered_at,"
        " last_heartbeat) VALUES (%s, 'claude-code', 'anthropic',"
        f" '{TEST_MODEL_ID}', 'primary', '[]', '/tmp/yok1674', 'wait', %s, %s)",
        (SESSION_ID, now, now))
    conn.commit()


def _build_item_fixture(conn) -> int:
    _seed_session(conn)
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, project_id,"
        " project_sequence, created_at, updated_at, source, frozen) "
        "VALUES (%s, 't', 'issue', 'refined-idea', 'high', 1, %s, %s, %s, "
        "'user', 0)",
        (ITEM_ID, ITEM_ID, _TS, _TS))
    cursor = conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id,"
        " claim_type, claimed_at, last_heartbeat)"
        " VALUES (%s, 'item', %s, 'exclusive', %s, %s) RETURNING id",
        (SESSION_ID, ITEM_ID, _TS, _TS))
    row = cursor.fetchone()
    cursor.close()
    conn.commit()
    return int(row[0])


def _seed_checkpoint(
    conn, *, chainable: bool, outcome: str,
) -> None:
    update_chain_checkpoint(
        conn, SESSION_ID, step=1, action="advance",
        chainable=chainable, handler_outcome=outcome)


def _eval_item(
    conn, *, intent: str = "readiness-check-blocked",
    allow_non_terminal: bool = False,
) -> ReleasePreconditionResult:
    return evaluate_release_precondition(
        conn, session_id=SESSION_ID, target=make_item_target(ITEM_ID),
        release_reason_intent=intent, allow_non_terminal=allow_non_terminal)


class TestEvaluateReleasePrecondition(unittest.TestCase):
    """Unit tests for the pure evaluator (AC-1..AC-4)."""

    def setUp(self) -> None:
        self.conn = _make_db()
        _seed_session(self.conn)

    def test_terminal_intent_short_circuits(self) -> None:
        # Terminal intent allows even on a bare DB without session/checkpoint.
        r = evaluate_release_precondition(
            _make_db(), session_id="x", target=make_item_target(ITEM_ID),
            release_reason_intent="completed")
        self.assertTrue(r.allowed)
        self.assertIsNone(r.refusal_reason)

    def test_non_terminal_chainable_refused_and_evidence_carried(self) -> None:
        """AC-3 negative: chainable=True + non-terminal outcome refuses."""
        _seed_checkpoint(self.conn, chainable=True, outcome=OUTCOME_COMPLETED)
        r = _eval_item(self.conn)
        self.assertFalse(r.allowed)
        self.assertEqual(r.refusal_reason, REFUSAL_NON_TERMINAL_RELEASE)
        self.assertEqual(r.checkpoint_chainable, True)
        self.assertEqual(r.checkpoint_outcome, OUTCOME_COMPLETED)

    def test_non_terminal_allowed_branches(self) -> None:
        """AC-3 positive: every durable-evidence branch allows."""
        cases = (
            ("non_chainable", False, OUTCOME_COMPLETED),
            ("blocked_outcome", True, OUTCOME_BLOCKED),
            ("interactive", False, OUTCOME_INTERACTIVE_CHECKPOINT),
        )
        for label, chainable, outcome in cases:
            with self.subTest(branch=label):
                conn = _make_db(); _seed_session(conn)
                _seed_checkpoint(conn, chainable=chainable, outcome=outcome)
                self.assertTrue(_eval_item(conn).allowed)

    def test_non_terminal_missing_checkpoint_allowed(self) -> None:
        r = _eval_item(self.conn)
        self.assertTrue(r.allowed)
        self.assertIsNone(r.checkpoint_outcome)
        self.assertIsNone(r.checkpoint_chainable)

    def test_allow_non_terminal_override_bypass(self) -> None:
        _seed_checkpoint(self.conn, chainable=True, outcome=OUTCOME_COMPLETED)
        self.assertTrue(
            _eval_item(self.conn, allow_non_terminal=True).allowed,
        )

    def test_epic_task_target_non_terminal_allowed(self) -> None:
        """AC-4: epic_task targets do not gate on checkpoint state."""
        _seed_checkpoint(self.conn, chainable=True, outcome=OUTCOME_COMPLETED)
        r = evaluate_release_precondition(
            self.conn, session_id=SESSION_ID,
            target=make_epic_task_target(EPIC_ID, 1),
            release_reason_intent="readiness-check-blocked")
        self.assertTrue(r.allowed)

def _read_released_at(conn, claim_id: int) -> object:
    row = conn.execute(
        "SELECT released_at FROM work_claims WHERE id = %s", (claim_id,),
    ).fetchone()
    return row["released_at"]


class TestReleaseWorkClaimIntegration(unittest.TestCase):
    """Integration tests through release_work_claim_for_execution."""

    def test_refused_release_does_not_mutate_work_claim(self) -> None:
        conn = _make_db()
        claim_id = _build_item_fixture(conn)
        _seed_checkpoint(conn, chainable=True, outcome=OUTCOME_COMPLETED)
        result = release_work_claim_for_execution(
            conn, SESSION_ID, make_item_target(ITEM_ID),
            "readiness-check-blocked")
        self.assertFalse(result["released"])
        self.assertEqual(
            result["failure_reason"], REFUSAL_NON_TERMINAL_RELEASE)
        self.assertEqual(result["checkpoint_chainable"], True)
        self.assertEqual(result["checkpoint_outcome"], OUTCOME_COMPLETED)
        self.assertIsNone(_read_released_at(conn, claim_id))

    def test_allowed_or_override_release_proceeds(self) -> None:
        """Non-chainable checkpoint OR allow_non_terminal=True both proceed."""
        for chainable, kwargs in (
            (False, {}),
            (True, {"allow_non_terminal": True}),
        ):
            with self.subTest(chainable=chainable):
                conn = _make_db()
                claim_id = _build_item_fixture(conn)
                _seed_checkpoint(
                    conn, chainable=chainable, outcome=OUTCOME_COMPLETED)
                result = release_work_claim_for_execution(
                    conn, SESSION_ID, make_item_target(ITEM_ID),
                    "readiness-check-blocked", **kwargs)
                self.assertTrue(result["released"])
                self.assertIsNotNone(_read_released_at(conn, claim_id))


def _capture_envelopes(target: callable) -> list[dict]:
    """Run ``target()`` with YOKE_EVENTS_CAPTURE bound, return parsed jsonl."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False) as handle:
        cap = handle.name
    prev = {k: os.environ.get(k)
            for k in ("YOKE_EVENTS_CAPTURE", "YOKE_EVENTS_FILE")}
    os.environ["YOKE_EVENTS_CAPTURE"] = "1"
    os.environ["YOKE_EVENTS_FILE"] = cap
    try:
        target()
    finally:
        for key, val in prev.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
    with open(cap, "r", encoding="utf-8") as handle:
        envelopes = [json.loads(s) for s in (l.strip() for l in handle) if s]
    os.unlink(cap)
    return envelopes


class TestRefusalEventEnvelope(unittest.TestCase):
    """AC-12: ItemClaimReleaseRefused envelope carries cold-start fields."""

    def test_refusal_envelope_carries_evidence_fields(self) -> None:
        conn = _make_db()
        claim_id = _build_item_fixture(conn)
        _seed_checkpoint(conn, chainable=True, outcome=OUTCOME_COMPLETED)

        envelopes = _capture_envelopes(lambda: release_work_claim_for_execution(
            conn, SESSION_ID, make_item_target(ITEM_ID),
            "readiness-check-blocked"))
        refused = [
            e for e in envelopes
            if e.get("event_name") == "ItemClaimReleaseRefused"
        ]
        self.assertEqual(
            len(refused), 1,
            f"want one ItemClaimReleaseRefused; got "
            f"{[e.get('event_name') for e in envelopes]}")
        ctx = refused[0].get("context") or {}
        expected = {
            "prior_owner_session_id": SESSION_ID,
            "item_id": str(ITEM_ID),
            "claim_id": claim_id,
            "release_reason_intent": "readiness-check-blocked",
            "checkpoint_chainable": True,
            "checkpoint_outcome": OUTCOME_COMPLETED,
            "failure_reason": REFUSAL_NON_TERMINAL_RELEASE,
        }
        for key, want in expected.items():
            self.assertIn(
                key, ctx,
                f"AC-12 field {key!r} missing; keys={sorted(ctx)}")
            self.assertEqual(ctx[key], want, f"field {key!r} mismatch")


class TestReleaseExitCodes(unittest.TestCase):
    """AC-14: release failure-to-exit map values are unique and stable."""

    def test_release_failure_exit_codes_are_unique(self) -> None:
        values = list(_RELEASE_FAILURE_TO_EXIT.values())
        self.assertEqual(
            len(set(values)), len(values),
            f"_RELEASE_FAILURE_TO_EXIT values must be unique; got {values}")
        # Spec pins the new exit code at 7 (next free after 6) and
        # distinct from the existing RELEASE_EXIT_ALREADY_TERMINAL (4).
        self.assertEqual(RELEASE_EXIT_PRECONDITION_REFUSED, 7)
        self.assertNotEqual(
            RELEASE_EXIT_PRECONDITION_REFUSED, RELEASE_EXIT_ALREADY_TERMINAL)
        # The new failure_reason must map to the new exit code.
        self.assertEqual(
            _RELEASE_FAILURE_TO_EXIT[REFUSAL_NON_TERMINAL_RELEASE],
            RELEASE_EXIT_PRECONDITION_REFUSED)


if __name__ == "__main__":
    unittest.main()
