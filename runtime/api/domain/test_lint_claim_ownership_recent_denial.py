"""Recent-denial branch coverage for lint_claim_ownership_mutations.

Split sibling of :mod:`test_lint_claim_ownership_mutations` (350-line
authored cap): owns the ``session_tool_calls`` + ``work_claims`` state
fixtures and the recent-attempt/live-holder verdict matrix.
"""

from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from yoke_core.domain import db_backend
from yoke_core.domain import lint_claim_ownership_mutations as lint
from yoke_core.domain.db_helpers import iso8601_now
from runtime.api.fixtures.file_test_db import init_test_db
from runtime.api.domain.test_lint_claim_ownership_mutations import (
    _AMBIENT,
    _payload,
)


def _state_schema(
    rows: list[tuple[str, str]],
    holders: list[tuple[str, int, bool]],
):
    """``init_test_db`` strategy: session_tool_calls + work_claims state.

    *rows* are ``(session_id, command_summary)`` recent Bash calls;
    *holders* are ``(session_id, item_id, released)`` work-claim rows.
    ``started_at`` uses ``iso8601_now`` (matching production) for the
    lexical ``started_at > %s`` compare.
    """

    def _apply() -> None:
        conn = db_backend.connect()
        try:
            conn.execute(
                "CREATE TABLE session_tool_calls (id INTEGER PRIMARY KEY, "
                "session_id TEXT NOT NULL, tool_use_id TEXT NOT NULL, "
                "tool_name TEXT, started_at TEXT NOT NULL, completed_at TEXT, "
                "outcome TEXT, command_summary TEXT)"
            )
            conn.execute(
                "CREATE TABLE work_claims (id INTEGER PRIMARY KEY, "
                "session_id TEXT NOT NULL, target_kind TEXT NOT NULL, "
                "item_id INTEGER, claim_type TEXT NOT NULL DEFAULT 'exclusive', "
                "claimed_at TEXT NOT NULL, last_heartbeat TEXT NOT NULL, "
                "released_at TEXT, release_reason TEXT)"
            )
            now = iso8601_now()
            for idx, (session_id, command) in enumerate(rows, start=1):
                conn.execute(
                    "INSERT INTO session_tool_calls (id, session_id, "
                    "tool_use_id, tool_name, started_at, completed_at, "
                    "outcome, command_summary) "
                    "VALUES (%s, %s, %s, 'Bash', %s, %s, 'failed', %s)",
                    (idx, session_id, f"tu-{idx}", now, now, command),
                )
            for idx, (session_id, item_id, released) in enumerate(
                holders, start=1,
            ):
                conn.execute(
                    "INSERT INTO work_claims (id, session_id, target_kind, "
                    "item_id, claimed_at, last_heartbeat, released_at) "
                    "VALUES (%s, %s, 'item', %s, %s, %s, %s)",
                    (idx, session_id, item_id, now, now,
                     now if released else None),
                )
            conn.commit()
        finally:
            conn.close()

    return _apply


@contextlib.contextmanager
def _seed_state_db(
    rows: list[tuple[str, str]],
    holders: list[tuple[str, int, bool]] = (),
):
    """Yield a backend-aware ``db_path`` token for a seeded state DB."""
    tmp = Path(tempfile.mkdtemp(prefix="claim-ownership-"))
    with init_test_db(
        tmp, apply_schema=_state_schema(list(rows), list(holders)),
    ) as path:
        yield path


class TestRecentDenialBranch(unittest.TestCase):
    def test_recent_attempt_with_live_foreign_holder_denies(self) -> None:
        rows = [(
            _AMBIENT,
            "python3 -m yoke_core.api.service_client claim-work --item YOK-1718",
        )]
        holders = [("holder-xyz", 1718, False)]
        cmd = "python3 -m yoke_core.cli.db_router items update 1718 spec --stdin"
        with _seed_state_db(rows, holders) as db_path:
            with mock.patch.object(lint, "_resolve_db_path", return_value=db_path):
                verdict = lint.evaluate_payload(_payload(cmd))
        self.assertIsNotNone(verdict)
        reason, family = verdict
        self.assertIn("claim-boundary bypass after live claim denial", reason)
        self.assertIn("Live holder: holder-xyz", reason)
        self.assertEqual(family, "db-router/items/update")

    def test_recent_attempt_allows_unrelated_item_and_session(self) -> None:
        for label, rows, holders, cmd in [
            (
                "unrelated item",
                [(
                    _AMBIENT,
                    "python3 -m yoke_core.api.service_client claim-work --item YOK-1712",
                )],
                [("holder-xyz", 1712, False)],
                "python3 -m yoke_core.cli.db_router items update 9999 spec --stdin",
            ),
            (
                "different session attempted, not ambient",
                [(
                    "other-session",
                    "python3 -m yoke_core.api.service_client claim-work --item YOK-1718",
                )],
                [("holder-xyz", 1718, False)],
                "python3 -m yoke_core.cli.db_router items update 1718 spec --stdin",
            ),
            (
                "claim-work succeeded (ambient is the holder)",
                [(
                    _AMBIENT,
                    "python3 -m yoke_core.api.service_client claim-work --item YOK-1718",
                )],
                [(_AMBIENT, 1718, False)],
                "python3 -m yoke_core.cli.db_router items update 1718 spec --stdin",
            ),
            (
                "holder released since the denial",
                [(
                    _AMBIENT,
                    "python3 -m yoke_core.api.service_client claim-work --item YOK-1718",
                )],
                [("holder-xyz", 1718, True)],
                "python3 -m yoke_core.cli.db_router items update 1718 spec --stdin",
            ),
        ]:
            with self.subTest(label):
                with _seed_state_db(rows, holders) as db_path:
                    with mock.patch.object(
                        lint, "_resolve_db_path", return_value=db_path,
                    ):
                        self.assertIsNone(lint.evaluate_payload(_payload(cmd)))

    def test_db_unavailable_fails_open(self) -> None:
        cmd = "python3 -m yoke_core.cli.db_router items update 1718 spec --stdin"
        with mock.patch.object(lint, "_resolve_db_path", return_value=None):
            # Postgres ignores a null path and would reach the DSN; force the
            # connect to fail so the fail-open branch is what's exercised.
            if db_backend.is_postgres():
                with mock.patch.object(
                    lint, "connect", side_effect=RuntimeError("no db"),
                ):
                    self.assertIsNone(lint.evaluate_payload(_payload(cmd)))
            else:
                self.assertIsNone(lint.evaluate_payload(_payload(cmd)))

    def test_null_command_summary_rows_fail_open(self) -> None:
        cmd = "python3 -m yoke_core.cli.db_router items update 1718 spec --stdin"
        with _seed_state_db([], [("holder-xyz", 1718, False)]) as db_path:
            conn = db_backend.connect()
            try:
                conn.execute(
                    "INSERT INTO session_tool_calls (id, session_id, "
                    "tool_use_id, tool_name, started_at) "
                    "VALUES (1, %s, 'tu-null', 'Bash', %s)",
                    (_AMBIENT, iso8601_now()),
                )
                conn.commit()
            finally:
                conn.close()
            with mock.patch.object(lint, "_resolve_db_path", return_value=db_path):
                self.assertIsNone(lint.evaluate_payload(_payload(cmd)))


if __name__ == "__main__":
    unittest.main()
