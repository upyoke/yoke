"""Frontier routed-ownership exclusion coverage.

Two defense classes: ``session_ended`` (transient SessionEnd signal) and
``non_terminal_intent`` (non-terminal ``work_claims.release_reason_intent``
stamped by the release path). Terminal intents never defend. The events
ledger is never consulted (telemetry-only events).
"""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.frontier_recent_owner import routed_ownership_exclusions


_INTENT_COLUMNS = (
    "    reason TEXT,\n"
    "    reason_intent TEXT,\n"
    "    release_reason_intent TEXT,\n"
)

_SCHEMA_TEMPLATE = """
CREATE TABLE IF NOT EXISTS harness_sessions (
    session_id TEXT PRIMARY KEY, executor TEXT NOT NULL,
    provider TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
    execution_lane TEXT NOT NULL DEFAULT 'primary', capabilities TEXT,
    workspace TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'wait',
    offered_at TEXT NOT NULL, last_heartbeat TEXT NOT NULL,
    ended_at TEXT, offer_envelope TEXT, actor_id INTEGER
);
CREATE TABLE IF NOT EXISTS work_claims (
    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL, item_id INTEGER,
    epic_id INTEGER, task_num INTEGER,
    process_key TEXT, conflict_group TEXT,
    claim_type TEXT NOT NULL DEFAULT 'exclusive',
    claimed_at TEXT NOT NULL, last_heartbeat TEXT NOT NULL,
{intent_columns}    released_at TEXT, release_reason TEXT
);
"""


def _schema(*, with_intent_columns: bool = True) -> str:
    return _SCHEMA_TEMPLATE.format(
        intent_columns=_INTENT_COLUMNS if with_intent_columns else "",
    )


def _iso(delta_s: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_s)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _insert_session(
    conn,
    session_id: str,
    *,
    heartbeat_age_s: int,
    ended: bool = False,
    offer_envelope: Optional[dict] = None,
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, offered_at, "
        " last_heartbeat, ended_at, offer_envelope) "
        "VALUES (%s, 'claude-code', 'anthropic', 'm', '/tmp', %s, %s, %s, %s)",
        (
            session_id,
            _iso(-heartbeat_age_s),
            _iso(-heartbeat_age_s),
            _iso() if ended else None,
            json.dumps(offer_envelope) if offer_envelope is not None else None,
        ),
    )
    conn.commit()


def _insert_released_claim(
    conn,
    session_id: str,
    item_id: int,
    *,
    released_age_s: int,
    release_reason: str = "session_ended",
    release_reason_intent: Optional[str] = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claim_type, claimed_at, "
        " last_heartbeat, released_at, release_reason) "
        "VALUES (%s, 'item', %s, 'exclusive', %s, %s, %s, %s) RETURNING id",
        (
            session_id,
            item_id,
            _iso(-released_age_s - 60),
            _iso(-released_age_s),
            _iso(-released_age_s),
            release_reason,
        ),
    )
    claim_id = int(cur.fetchone()[0])
    if release_reason_intent is not None:
        conn.execute(
            "UPDATE work_claims SET release_reason_intent = %s "
            "WHERE id = %s",
            (release_reason_intent, claim_id),
        )
    conn.commit()
    return claim_id


class TestRoutedOwnershipExclusions(unittest.TestCase):
    """Branch A — historical ``session_ended`` defense (preserved)."""

    def _build_conn(self, *, with_intent_columns: bool = True):
        """Disposable per-test Postgres database carrying the frontier
        custom schema, with ``YOKE_PG_DSN`` repointed at it. The DB and DSN
        are restored on test teardown.
        """
        from runtime.api.fixtures import pg_testdb
        from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

        name = pg_testdb.create_test_database()
        prior_dsn = os.environ.get(db_backend.PG_DSN_ENV)
        os.environ[db_backend.PG_DSN_ENV] = pg_testdb.dsn_for_test_database(name)
        conn = pg_testdb.connect_test_database(name)

        def _teardown() -> None:
            conn.close()
            if prior_dsn is not None:
                os.environ[db_backend.PG_DSN_ENV] = prior_dsn
            else:
                os.environ.pop(db_backend.PG_DSN_ENV, None)
            pg_testdb.drop_test_database(name)

        self.addCleanup(_teardown)

        apply_fixture_ddl(conn, _schema(with_intent_columns=with_intent_columns))
        return conn

    def test_session_ended_branch_defends_when_owner_alive(self) -> None:
        conn = self._build_conn()
        _insert_session(conn, "owner", heartbeat_age_s=10)
        _insert_released_claim(conn, "owner", 17, released_age_s=10)
        excluded = routed_ownership_exclusions(
            conn, window_s=300, requesting_session_id="other",
        )
        self.assertIn("YOK-17", excluded)
        detail = excluded["YOK-17"]
        self.assertEqual(detail["prior_owner_session_id"], "owner")
        self.assertEqual(detail["defense_class"], "session_ended")
        self.assertEqual(detail["release_reason_intent"], "session_ended")
        self.assertIsInstance(detail["latest_claim_id"], int)

    def test_session_ended_branch_skips_when_owner_session_ended(self) -> None:
        conn = self._build_conn()
        _insert_session(conn, "owner", heartbeat_age_s=10, ended=True)
        _insert_released_claim(conn, "owner", 18, released_age_s=10)
        excluded = routed_ownership_exclusions(
            conn, window_s=300, requesting_session_id="other",
        )
        self.assertEqual(excluded, {})

    def test_not_defended_past_window(self) -> None:
        conn = self._build_conn()
        _insert_session(conn, "owner", heartbeat_age_s=99999)
        _insert_released_claim(conn, "owner", 19, released_age_s=99999)
        excluded = routed_ownership_exclusions(
            conn, window_s=300, requesting_session_id="other",
        )
        self.assertEqual(excluded, {})

    def test_requesting_session_not_defended_against_itself(self) -> None:
        conn = self._build_conn()
        _insert_session(conn, "self", heartbeat_age_s=10)
        _insert_released_claim(conn, "self", 20, released_age_s=10)
        excluded = routed_ownership_exclusions(
            conn, window_s=300, requesting_session_id="self",
        )
        self.assertEqual(excluded, {})

    def test_only_most_recent_claim_row_drives_defense(self) -> None:
        conn = self._build_conn()
        _insert_session(conn, "owner", heartbeat_age_s=10)
        _insert_released_claim(conn, "owner", 21, released_age_s=20)
        _insert_released_claim(
            conn, "owner", 21, released_age_s=5, release_reason="completed",
        )
        excluded = routed_ownership_exclusions(
            conn, window_s=300, requesting_session_id="other",
        )
        self.assertNotIn("YOK-21", excluded)

    # Branch B — non-terminal release-intent defense (release-gap defense).

    def test_non_terminal_intent_branch_defends(self) -> None:
        conn = self._build_conn()
        _insert_session(conn, "owner", heartbeat_age_s=10)
        claim_id = _insert_released_claim(
            conn, "owner", 22, released_age_s=10, release_reason="released",
            release_reason_intent="readiness-check-blocked",
        )
        excluded = routed_ownership_exclusions(
            conn, window_s=300, requesting_session_id="other",
        )
        self.assertIn("YOK-22", excluded)
        detail = excluded["YOK-22"]
        self.assertEqual(detail["defense_class"], "non_terminal_intent")
        self.assertEqual(
            detail["release_reason_intent"], "readiness-check-blocked",
        )
        self.assertEqual(detail["latest_claim_id"], claim_id)

    def test_terminal_intent_does_not_defend(self) -> None:
        conn = self._build_conn()
        _insert_session(conn, "owner", heartbeat_age_s=10)
        _insert_released_claim(
            conn, "owner", 23, released_age_s=10, release_reason="released",
            release_reason_intent="completed",
        )
        excluded = routed_ownership_exclusions(
            conn, window_s=300, requesting_session_id="other",
        )
        self.assertNotIn("YOK-23", excluded)

    def test_completed_release_column_does_not_defend(self) -> None:
        conn = self._build_conn()
        _insert_session(conn, "owner", heartbeat_age_s=10)
        _insert_released_claim(
            conn, "owner", 24, released_age_s=10, release_reason="completed",
        )
        excluded = routed_ownership_exclusions(
            conn, window_s=300, requesting_session_id="other",
        )
        self.assertNotIn("YOK-24", excluded)

    def test_detail_dict_includes_checkpoint_outcome(self) -> None:
        conn = self._build_conn()
        _insert_session(
            conn, "owner", heartbeat_age_s=10,
            offer_envelope={
                "chain_checkpoint": {
                    "step": 1, "action": "readiness-check",
                    "chainable": True, "handler_outcome": "readiness-blocked",
                    "completed_at": _iso(-10),
                },
            },
        )
        _insert_released_claim(
            conn, "owner", 25, released_age_s=10, release_reason="released",
            release_reason_intent="readiness-check-blocked",
        )
        excluded = routed_ownership_exclusions(
            conn, window_s=300, requesting_session_id="other",
        )
        self.assertIn("YOK-25", excluded)
        self.assertEqual(
            excluded["YOK-25"]["checkpoint_outcome"], "readiness-blocked",
        )

    def test_missing_intent_column_keeps_session_ended_branch(self) -> None:
        """Pre-cutover fixture shape: NULL intent means no non-terminal
        defense, but the session_ended column branch still defends."""
        conn = self._build_conn(with_intent_columns=False)
        _insert_session(conn, "owner", heartbeat_age_s=10)
        _insert_released_claim(conn, "owner", 26, released_age_s=10)
        _insert_session(conn, "other-owner", heartbeat_age_s=10)
        _insert_released_claim(
            conn, "other-owner", 27, released_age_s=10,
            release_reason="released",
        )
        excluded = routed_ownership_exclusions(
            conn, window_s=300, requesting_session_id="other",
        )
        self.assertIn("YOK-26", excluded)
        self.assertNotIn("YOK-27", excluded)


if __name__ == "__main__":
    unittest.main()
