"""Verdict tests for the duplicate-Monitor PreToolUse rule.

Focused sibling of ``test_lint_long_command_polling_monitor_rules`` so
both authored test files stay under the 350-line cap. Covers:

- identical re-arm denied (warn and deny modes for the AC-5 split)
- different-filter re-arm denied (AC-3 capture-file equivalence)
- foreign-capture allowed (different capture file is its own lane)
- post-completion second Monitor against same capture also denied
  (session-spanning fire-once contract — operational data showed this
  was the dominant wake-loop shape)
- ``# lint:no-monitor-duplicate-check`` audit-only suppression
- ``evaluate_duplicate_monitor`` callable directly (AC-1 surface)

Run-level audit-event outcome propagation lives in
``test_lint_long_command_polling_run.py``. Most verdict cases mock
``_captures_targeted_in_session``; the DB-backed tests below exercise
the Started-row lookup directly against an isolated temp DB.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)
from yoke_core.domain import (
    lint_long_command_polling_evaluate as lint,
    lint_long_command_polling_monitor_duplicate as monitor_dup,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.lint_long_command_polling_test_helpers import (
    _non_bash_payload,
)


def _monitor_payload(
    command: str,
    *,
    session_id: str = "sess-monitor",
    turn_id: str = "turn-monitor",
    tool_use_id: str = "tu-monitor-new",
) -> dict:
    """PreToolUse payload for a Monitor invocation."""
    return {
        "tool_name": "Monitor",
        "tool_input": {"command": command},
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "turn_id": turn_id,
    }


_CAPTURE_X = "/tmp/yoke-pytest.progress.AAAA"
_CAPTURE_Y = "/tmp/yoke-pytest.progress.BBBB"


class _DuplicateMonitorBase(unittest.TestCase):
    """Shared mode + armed-monitor patch helpers."""

    def setUp(self) -> None:
        # Default to warn mode so test names alone signal mode-pinning.
        self._mode_patch = mock.patch.object(
            monitor_dup, "_read_lint_mode", return_value="warn"
        )
        self._mode_patch.start()
        self.addCleanup(self._mode_patch.stop)
        # Avoid touching the real DB — tests inject the armed set directly.
        self._db_patch = mock.patch.object(
            monitor_dup, "_db_available", return_value=True
        )
        self._db_patch.start()
        self.addCleanup(self._db_patch.stop)

    def _patch_armed(self, armed_pairs: list[tuple[str, str]]):
        """Mock the targeted-captures lookup so tests don't need a live DB."""
        return mock.patch.object(
            monitor_dup,
            "_captures_targeted_in_session",
            return_value=armed_pairs,
        )


class TestDuplicateMonitorDetection(_DuplicateMonitorBase):
    """Capture-file equivalence drives the verdict; filter is irrelevant."""

    def test_identical_rearm_denied_warn_mode(self) -> None:
        # AC-9 case 1: identical re-arm denied. Verdict is the configured
        # mode (warn here); ctx.outcome is "denied" and the reason names
        # the prior tool_use_id for the TaskStop workaround.
        with self._patch_armed([("tu-monitor-prior", _CAPTURE_X)]):
            result = lint.evaluate_payload(
                _monitor_payload(
                    f"python3 -m yoke_core.tools.watch_tail {_CAPTURE_X}"
                )
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, reason, ctx = result
        self.assertEqual(verdict, "warn")
        self.assertEqual(ctx.get("outcome"), "denied")
        self.assertIn("tu-monitor-prior", reason)
        self.assertIn(_CAPTURE_X, reason)

    def test_identical_rearm_denied_deny_mode(self) -> None:
        # AC-5 deny-mode: verdict is "deny" and reason carries DENIED verb.
        with mock.patch.object(
            monitor_dup, "_read_lint_mode", return_value="deny",
        ), self._patch_armed([("tu-monitor-prior", _CAPTURE_X)]):
            result = lint.evaluate_payload(
                _monitor_payload(
                    f"python3 -m yoke_core.tools.watch_tail {_CAPTURE_X}"
                )
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, reason, _ctx = result
        self.assertEqual(verdict, "deny")
        self.assertIn("DENIED", reason)

    def test_different_filter_rearm_against_same_capture_denied(self) -> None:
        # Capture-file equivalence is the key, not filter equivalence.
        # The candidate uses bare tail -f with a different grep filter;
        # the prior armed Monitor used watch_tail. Same capture file -> deny.
        with self._patch_armed([("tu-monitor-prior", _CAPTURE_X)]):
            result = lint.evaluate_payload(
                _monitor_payload(
                    f"tail -f {_CAPTURE_X} | grep --line-buffered FAILED"
                )
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, reason, ctx = result
        self.assertEqual(verdict, "warn")
        self.assertEqual(ctx.get("outcome"), "denied")
        self.assertIn(_CAPTURE_X, reason)

    def test_monitor_on_different_capture_allowed(self) -> None:
        # AC-9 case 3: armed Monitor on capture X must not block
        # arming a Monitor against capture Y. Each capture-file lane is
        # independently fire-once.
        with self._patch_armed([("tu-monitor-prior", _CAPTURE_X)]):
            self.assertIsNone(
                lint.evaluate_payload(
                    _monitor_payload(
                        f"python3 -m yoke_core.tools.watch_tail {_CAPTURE_Y}"
                    )
                )
            )

    def test_second_monitor_after_prior_completes_denied(self) -> None:
        # Session-spanning fire-once: a completed prior Monitor against
        # the same capture still trips the rule. The targeted-captures
        # lookup returns the earlier Monitor's tool_use_id regardless of
        # whether it has terminated.
        with self._patch_armed([("tu-monitor-completed", _CAPTURE_X)]):
            result = lint.evaluate_payload(
                _monitor_payload(
                    f"python3 -m yoke_core.tools.watch_tail {_CAPTURE_X}"
                )
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, reason, ctx = result
        self.assertEqual(verdict, "warn")
        self.assertEqual(ctx.get("outcome"), "denied")
        self.assertIn("tu-monitor-completed", reason)
        self.assertIn(_CAPTURE_X, reason)

    def test_no_prior_monitor_allows_first_arm(self) -> None:
        # First Monitor against a capture passes through.
        with self._patch_armed([]):
            self.assertIsNone(
                lint.evaluate_payload(
                    _monitor_payload(
                        f"python3 -m yoke_core.tools.watch_tail {_CAPTURE_X}"
                    )
                )
            )

    def test_monitor_no_capture_extracted_allowed(self) -> None:
        # When the Monitor command does not reference a /tmp capture file
        # (e.g., user wired an unusual filter), the lint cannot establish
        # equivalence and must pass through rather than guess.
        with self._patch_armed([("tu-monitor-prior", _CAPTURE_X)]):
            self.assertIsNone(
                lint.evaluate_payload(_monitor_payload("watch some-other-cmd"))
            )

    def test_non_monitor_tool_unaffected(self) -> None:
        # The Monitor branch must not intercept other tool calls.
        with self._patch_armed([("tu-monitor-prior", _CAPTURE_X)]):
            self.assertIsNone(
                lint.evaluate_payload(
                    _non_bash_payload("Read", tool_input={"file_path": "/x"})
                )
            )


class TestDuplicateMonitorSuppression(_DuplicateMonitorBase):
    """The `# lint:no-monitor-duplicate-check` token is audit-only."""

    def test_suppression_token_records_attempt_but_denies(self) -> None:
        # Token detection switches ctx.outcome to suppression_attempted
        # but verdict still fires (mode-pinned).
        with mock.patch.object(
            monitor_dup, "_read_lint_mode", return_value="deny",
        ), self._patch_armed([("tu-monitor-prior", _CAPTURE_X)]):
            result = lint.evaluate_payload(
                _monitor_payload(
                    f"python3 -m yoke_core.tools.watch_tail {_CAPTURE_X}  "
                    "# lint:no-monitor-duplicate-check"
                )
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, reason, ctx = result
        self.assertEqual(verdict, "deny")
        self.assertEqual(ctx.get("outcome"), "suppression_attempted")
        self.assertIn("recorded for audit", reason)
        self.assertIn("does NOT unblock", reason)


class TestCapturesTargetedLookup(unittest.TestCase):
    """DB-backed lookup returns every Monitor-targeted capture in session.

    Includes still-armed (open) and already-completed Monitor rows from
    ``session_tool_calls``; the capture path is parsed from
    ``command_summary``. Synthetic rows use Yoke's canonical ISO
    timestamp so the lookback window accepts them.
    """

    def _build_db(self) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ctx = init_test_db(Path(tmp.name), apply_schema=apply_fixture_schema_ddl)
        db_path = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        return db_path

    def _insert_monitor_call(
        self, db_path: str, tool_use_id: str, command: str = "",
        *, completed: bool = False,
    ) -> None:
        conn = connect_test_db(db_path)
        try:
            now = iso8601_now()
            conn.execute(
                """INSERT INTO session_tool_calls
                   (session_id, tool_use_id, tool_name, started_at,
                    completed_at, outcome, command_summary)
                   VALUES (%s, %s, 'Monitor', %s, %s, %s, %s)""",
                (
                    "sess-monitor",
                    tool_use_id,
                    now,
                    now if completed else None,
                    "completed" if completed else None,
                    command or None,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def test_open_monitor_row_returned(self) -> None:
        db_path = self._build_db()
        self._insert_monitor_call(
            db_path,
            "tu-open",
            f"python3 -m yoke_core.tools.watch_tail {_CAPTURE_X}",
        )

        self.assertEqual(
            monitor_dup._captures_targeted_in_session(db_path, "sess-monitor"),
            [("tu-open", _CAPTURE_X)],
        )

    def test_completed_monitor_row_still_counts(self) -> None:
        # Session-spanning fire-once: a Monitor whose row has already
        # closed still blocks a fresh Monitor against the same capture.
        db_path = self._build_db()
        self._insert_monitor_call(
            db_path,
            "tu-done",
            f"python3 -m yoke_core.tools.watch_tail {_CAPTURE_X}",
            completed=True,
        )

        self.assertEqual(
            monitor_dup._captures_targeted_in_session(db_path, "sess-monitor"),
            [("tu-done", _CAPTURE_X)],
        )


class TestEvaluateDuplicateMonitorEntrypoint(_DuplicateMonitorBase):
    """The public ``evaluate_duplicate_monitor`` entrypoint surface."""

    def test_direct_call_returns_same_verdict_as_evaluate_payload(self) -> None:
        with self._patch_armed([("tu-monitor-prior", _CAPTURE_X)]):
            direct = monitor_dup.evaluate_duplicate_monitor(
                _monitor_payload(
                    f"python3 -m yoke_core.tools.watch_tail {_CAPTURE_X}"
                )
            )
            routed = lint.evaluate_payload(
                _monitor_payload(
                    f"python3 -m yoke_core.tools.watch_tail {_CAPTURE_X}"
                )
            )
        self.assertIsNotNone(direct)
        self.assertEqual(direct, routed)

    def test_public_reexport_at_entry_point(self) -> None:
        # AC-1 contract: callers can import the function from the
        # entry-point module path, not just the duplicate-Monitor sibling.
        from yoke_core.domain import lint_long_command_polling as entry

        self.assertIs(
            entry.evaluate_duplicate_monitor,
            monitor_dup.evaluate_duplicate_monitor,
        )


if __name__ == "__main__":
    unittest.main()
