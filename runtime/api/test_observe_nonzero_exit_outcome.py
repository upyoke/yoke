"""Regression coverage for nonzero-exit -> failed outcome end to end.

These tests drive Bash ``PostToolUse`` payloads through the real
``parse_hook_event -> detect_anomalies -> build_envelope -> insert_event``
pipeline and assert that the resulting ``events`` row carries the
truthful first-class columns (``event_outcome``, ``exit_code``,
``event_name``). They live in this split file because the parent
``test_observe_codex_bash.py`` is at 307/350 lines and would exceed the
350-line hard cap if grown further.

All assertions reference the ``OUTCOME_*`` constants from
``yoke_core.domain.events_tool_call_outcome`` rather than string
literals, so the contract is enforced at one source of truth.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.events_tool_call_outcome import (
    OUTCOME_COMPLETED,
    OUTCOME_DENIED,
    OUTCOME_FAILED,
    OUTCOMES,
)
from yoke_core.domain.observe import (
    build_envelope,
    detect_anomalies,
    insert_event,
    parse_hook_event,
)
from runtime.api.observe_test_helpers import make_memory_db


@pytest.fixture
def memory_db():
    conn = make_memory_db()
    yield conn
    conn.close()


def _drive_pipeline(conn, payload, *, hook_event="PostToolUse"):
    """Run a hook payload through parse -> anomalies -> envelope -> insert."""
    rec = parse_hook_event(payload, hook_event=hook_event)
    assert rec is not None, "parse_hook_event should never drop these payloads"
    detect_anomalies(rec)
    envelope = build_envelope(rec)
    insert_event(conn, envelope)
    return rec, envelope


def _read_row(conn, tool_use_id):
    cursor = conn.execute(
        "SELECT event_name, event_outcome, exit_code, anomaly_flags, envelope "
        "FROM events WHERE tool_use_id = %s",
        (tool_use_id,),
    )
    row = cursor.fetchone()
    assert row is not None, f"no events row for tool_use_id={tool_use_id}"
    return {
        "event_name": row[0],
        "event_outcome": row[1],
        "exit_code": row[2],
        "anomaly_flags": row[3],
        "envelope": json.loads(row[4]),
    }


class TestNonzeroExitWritesFailedRow:
    """``Exit code N`` (N>0) lands as ``HarnessToolCallFailed`` / ``failed``."""

    def test_exit_code_1_records_failed_with_real_exit(self, memory_db):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "false"},
            "tool_response": {"content": "Exit code 1"},
            "tool_use_id": "tu-exit-1",
        }
        rec, _ = _drive_pipeline(memory_db, payload)
        assert rec.is_failure is True
        assert rec.exit_code == 1

        row = _read_row(memory_db, "tu-exit-1")
        assert row["event_outcome"] == OUTCOME_FAILED
        assert row["event_name"] == "HarnessToolCallFailed"
        assert row["exit_code"] == 1

    def test_exit_code_7_records_failed_with_real_exit(self, memory_db):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "exit 7"},
            "tool_response": {"content": "Exit code 7"},
            "tool_use_id": "tu-exit-7",
        }
        rec, _ = _drive_pipeline(memory_db, payload)
        assert rec.is_failure is True
        assert rec.exit_code == 7

        row = _read_row(memory_db, "tu-exit-7")
        assert row["event_outcome"] == OUTCOME_FAILED
        assert row["event_name"] == "HarnessToolCallFailed"
        assert row["exit_code"] == 7

    def test_exit_code_127_command_not_found_records_failed(self, memory_db):
        # 127 is a particularly common "command not found" exit. The parser
        # has TWO independent paths to failure here: the "Exit code 127"
        # text AND the defense-in-depth "command not found" stderr match.
        # Either way, the row must end up as a HarnessToolCallFailed.
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "bogus_binary"},
            "tool_response": {
                "content": "zsh: command not found: bogus_binary\nExit code 127"
            },
            "tool_use_id": "tu-exit-127",
        }
        rec, _ = _drive_pipeline(memory_db, payload)
        assert rec.is_failure is True
        assert rec.exit_code == 127

        row = _read_row(memory_db, "tu-exit-127")
        assert row["event_outcome"] == OUTCOME_FAILED
        assert row["event_name"] == "HarnessToolCallFailed"
        assert row["exit_code"] == 127


class TestPermissionDeniedWritesDeniedOutcome:
    """A permission-decision payload lands with ``event_outcome=denied``."""

    def test_permission_decision_failure_records_denied(self, memory_db):
        # PostToolUseFailure payload that carries a top-level
        # ``permissionDecision`` is the harness refusing to execute.
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /etc"},
            "tool_response": {"content": ""},
            "error": "Permission denied by policy",
            "permissionDecision": {"decision": "deny", "reason": "policy"},
            "tool_use_id": "tu-denied-1",
        }
        rec, _ = _drive_pipeline(memory_db, payload, hook_event="PostToolUseFailure")
        assert rec.is_failure is True
        assert rec.has_permission_decision is True

        row = _read_row(memory_db, "tu-denied-1")
        assert row["event_outcome"] == OUTCOME_DENIED
        # event_name is "HarnessToolCallFailed" for both denied and
        # failed outcomes (no separate Denied event name in the catalog).
        assert row["event_name"] == "HarnessToolCallFailed"


class TestEnumRoundtrip:
    """Every emitted ``event_outcome`` must be a member of ``OUTCOMES``."""

    def test_failed_outcome_is_member_of_outcomes(self, memory_db):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "false"},
            "tool_response": {"content": "Exit code 1"},
            "tool_use_id": "tu-roundtrip-failed",
        }
        _drive_pipeline(memory_db, payload)
        row = _read_row(memory_db, "tu-roundtrip-failed")
        assert row["event_outcome"] in OUTCOMES

    def test_completed_outcome_is_member_of_outcomes(self, memory_db):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
            "tool_response": {"content": "hi\n"},
            "tool_use_id": "tu-roundtrip-ok",
        }
        _drive_pipeline(memory_db, payload)
        row = _read_row(memory_db, "tu-roundtrip-ok")
        assert row["event_outcome"] in OUTCOMES
        assert row["event_outcome"] == OUTCOME_COMPLETED


class TestNonzeroExitAndAnomalyAreIndependent:
    """AC-8: a failed row has both ``event_outcome=failed`` AND ``nonzero_exit``."""

    def test_failed_outcome_carries_nonzero_exit_anomaly(self, memory_db):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "exit 2"},
            "tool_response": {"content": "Exit code 2"},
            "tool_use_id": "tu-independent",
        }
        _drive_pipeline(memory_db, payload)
        row = _read_row(memory_db, "tu-independent")

        # First-class outcome AND anomaly flag are BOTH present. The
        # anomaly is diagnostic metadata; the outcome is the audit truth.
        # Neither is a substitute for the other.
        assert row["event_outcome"] == OUTCOME_FAILED
        anomaly_flags = (row["anomaly_flags"] or "").split(",")
        assert "nonzero_exit" in anomaly_flags
