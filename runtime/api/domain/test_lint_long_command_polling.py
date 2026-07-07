"""Tests for ``yoke_core.domain.lint_long_command_polling`` — extract/config/lookup.

The original module covered every flavor of the long-command polling lint. It
is now split across siblings so each authored file stays under the 350-line
limit. ``evaluate_payload`` cases live in ``test_lint_long_command_polling_evaluate``,
and ``run`` cases live in ``test_lint_long_command_polling_run``. This file
covers the smaller helper extraction, mode-config, recent-command lookup,
mtime signal, and session-scoping checks.

Most extract/lookup helpers live on the evaluate sibling
(``lint_long_command_polling_evaluate``) — the alias ``lint_eval`` points
there. The machine-config reader lives on the config sibling
(``lint_long_command_polling_config``) — the alias ``lint_config`` points
there. The entry-point module re-exports both for the FR-5 contract; the
alias ``lint_entry`` points to the entry-point.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)
from yoke_core.domain import lint_long_command_polling as lint_entry
from yoke_core.domain import (
    lint_long_command_polling_config as lint_config,
)
from yoke_core.domain import (
    lint_long_command_polling_evaluate as lint_eval,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.lint_long_command_polling_test_helpers import (
    _bash_payload,
)


class TestExtractHelpers(unittest.TestCase):
    def test_peek_capture_file_tail(self) -> None:
        self.assertEqual(
            lint_eval._extract_peek_capture_file("tail -80 /tmp/yoke-pytest.out"),
            "/tmp/yoke-pytest.out",
        )

    def test_peek_capture_file_head(self) -> None:
        self.assertEqual(
            lint_eval._extract_peek_capture_file("head -20 /tmp/run.log"),
            "/tmp/run.log",
        )

    def test_peek_capture_file_cat_pipe_tail(self) -> None:
        self.assertEqual(
            lint_eval._extract_peek_capture_file("cat /tmp/run.log | tail -n 50"),
            "/tmp/run.log",
        )

    def test_peek_not_matched_on_kickoff(self) -> None:
        # A Bash command that both writes to and tails the file is a kickoff,
        # not a peek. The redirect takes precedence.
        self.assertIsNone(
            lint_eval._extract_peek_capture_file(
                "sh test.sh > /tmp/run.out 2>&1; tail -80 /tmp/run.out"
            )
        )

    def test_peek_not_matched_non_tmp(self) -> None:
        self.assertIsNone(
            lint_eval._extract_peek_capture_file("tail -80 ./local-log.txt")
        )

    def test_sleep_cadence_extracted(self) -> None:
        self.assertEqual(
            lint_eval._extract_sleep_cadence("sleep 10 && tail -20 /tmp/foo.out"),
            10,
        )

    def test_sleep_cadence_semicolon(self) -> None:
        self.assertEqual(
            lint_eval._extract_sleep_cadence("sleep 5; cat /tmp/foo.out"),
            5,
        )

    def test_sleep_cadence_not_present(self) -> None:
        self.assertIsNone(
            lint_eval._extract_sleep_cadence("tail -80 /tmp/foo.out")
        )

    def test_suppression_token(self) -> None:
        self.assertTrue(lint_eval._has_suppression("tail /tmp/x  # lint:no-polling-check"))
        self.assertFalse(lint_eval._has_suppression("tail /tmp/x"))


class TestLintModeConfig(unittest.TestCase):
    def test_read_lint_mode_delegates_to_registry(self) -> None:
        # Mode now resolves through the single lint_config registry; per-key /
        # per-value parsing + the protected clamp are covered by test_lint_config.
        from yoke_core.domain import lint_config as registry

        with mock.patch.object(
            registry, "resolve_mode_for_payload", return_value="warn",
        ) as m:
            self.assertEqual(lint_entry._read_lint_mode(), "warn")
        m.assert_called_once_with("lint_long_command_polling", None)


class TestRecentCommandLookup(unittest.TestCase):
    def test_reads_session_tool_calls_command_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, init_test_db(
            Path(tmp), apply_schema=apply_fixture_schema_ddl,
        ) as db_path:
            conn = connect_test_db(db_path)
            now = iso8601_now()
            conn.execute(
                """
                INSERT INTO session_tool_calls (
                    session_id, tool_use_id, tool_name, started_at,
                    completed_at, outcome, command_summary
                ) VALUES (%s, 'tu-1', 'Bash', %s, %s, 'completed', %s)
                """,
                ("sess-main", now, now, "tail -80 /tmp/foo.out"),
            )
            # Open (still-running) calls are not "recent completed commands".
            conn.execute(
                """
                INSERT INTO session_tool_calls (
                    session_id, tool_use_id, tool_name, started_at,
                    command_summary
                ) VALUES (%s, 'tu-open', 'Bash', %s, %s)
                """,
                ("sess-main", now, "sleep 600"),
            )
            conn.commit()
            conn.close()

            rows = lint_eval._recent_bash_commands(db_path, "sess-main")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "tu-1")
        self.assertEqual(rows[0][2], "tail -80 /tmp/foo.out")


class TestMtimeSignal(unittest.TestCase):
    def test_owning_command_still_running_recent_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            capture = os.path.join(tmp, "capture.out")
            with open(capture, "w", encoding="utf-8") as fh:
                fh.write("x\n")
            # freshly written — should be considered "still running"
            self.assertTrue(lint_eval._owning_command_still_running(capture))

    def test_owning_command_completed_old_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            capture = os.path.join(tmp, "capture.out")
            with open(capture, "w", encoding="utf-8") as fh:
                fh.write("x\n")
            old = time.time() - 300
            os.utime(capture, (old, old))
            self.assertFalse(lint_eval._owning_command_still_running(capture))

    def test_owning_command_missing_file(self) -> None:
        self.assertFalse(
            lint_eval._owning_command_still_running("/tmp/nonexistent-file-12345.out")
        )


class TestSessionScoping(unittest.TestCase):
    """Ensure repeated peeks in a different session do not cross-contaminate."""

    def test_cross_session_peeks_not_counted(self) -> None:
        other_session_events = [
            ("turn-x", "2026-04-24T12:00:00", "tail -80 /tmp/foo.out"),
        ]

        def fake_recent(db_path: str, session_id: str, **_kwargs: object) -> list:
            if session_id == "sess-main":
                return []
            return other_session_events

        with mock.patch.object(
                lint_eval, "_owning_command_still_running", return_value=True
             ), \
             mock.patch.object(lint_eval, "_db_available", return_value=True), \
             mock.patch.object(lint_eval, "_recent_bash_commands", side_effect=fake_recent):
            self.assertIsNone(
                lint_eval.evaluate_payload(
                    _bash_payload(
                        "tail -80 /tmp/foo.out",
                        session_id="sess-main",
                        turn_id="turn-1",
                    )
                )
            )


if __name__ == "__main__":
    unittest.main()
