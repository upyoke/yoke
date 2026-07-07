"""Cutoff-specific tests for the claim-boundary-audit HC.

The sibling :mod:`test_doctor_hc_claim_boundary_audit` already covers
PASS / WARN / FAIL semantics. This module covers the machine-config
event-id cutoff seeded by ``hc_claim_boundary_audit_min_event_id``:
pre-cutoff events suppress to PASS, at/after-cutoff events still
classify per the existing rules.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Iterator

import pytest

from yoke_core.domain import check_claim_boundary_audit_cutoff as _cutoff
from yoke_core.engines.doctor_hc_claim_boundary_audit import (
    hc_claim_boundary_audit,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[dict]:
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield {"conn": conn}
        finally:
            conn.close()


@pytest.fixture
def patch_cutoff(monkeypatch: pytest.MonkeyPatch):
    def _set(value: int) -> None:
        monkeypatch.setattr(
            _cutoff, "read_min_event_id_cutoff", lambda: value,
        )
    return _set


def _sid(label: str) -> str:
    return f"{label * 8}-{label * 4}-{label * 4}-{label * 4}-{label * 12}"


def _add_session(conn: Any, sid: str) -> None:
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider,"
        " model, workspace, mode, offered_at, last_heartbeat)"
        " VALUES (%s, 'claude-desktop', 'anthropic', 'claude-opus-4-7',"
        " '/tmp/ws', 'charge', '2026-05-17T11:00:00Z',"
        " '2026-05-17T11:00:00Z')",
        (sid,),
    )
    conn.commit()


def _add_claim(
    conn: Any, sid: str, item_id: int,
    claimed_at: str = "2026-05-17T11:00:00Z",
) -> None:
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id,"
        " claimed_at, last_heartbeat)"
        " VALUES (%s, 'item', %s, %s, %s)",
        (sid, item_id, claimed_at, claimed_at),
    )
    conn.commit()


def _add_event_with_id(
    conn: Any, *, target_id: int, name: str, sid: str,
    item_id: int, context: dict,
    created_at: str = "2026-05-17T12:00:00Z",
) -> int:
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_name": name,
        "session_id": sid,
        "context": context,
    }
    conn.execute(
        "INSERT INTO events (id, event_id, source_type, session_id,"
        " severity, event_kind, event_type, event_name, item_id, envelope,"
        " created_at)"
        " VALUES (%s, %s, 'backend', %s, 'INFO', 'lifecycle', 'function_call',"
        " %s, %s, %s, %s)",
        (target_id, envelope["event_id"], sid, name, str(item_id),
         json.dumps(envelope), created_at),
    )
    conn.commit()
    return target_id


def _run(conn: Any) -> RecordCollector:
    rec = RecordCollector()
    hc_claim_boundary_audit(conn, DoctorArgs(), rec)
    return rec


def test_cutoff_suppresses_pre_cutoff_event_ids(env, patch_cutoff):
    """Pre-cutoff violations grandfather to PASS — historical residue
    after the writer-side prevention tickets land."""
    conn = env["conn"]
    holder, other = _sid("a"), _sid("b")
    _add_session(conn, holder)
    _add_session(conn, other)
    _add_claim(conn, holder, 900)
    _add_event_with_id(
        conn, target_id=500, name="YokeFunctionCalled", sid=other,
        item_id=900, context={"function": "items.structured_field.replace"},
    )
    patch_cutoff(1000)
    rec = _run(conn)
    assert len(rec.results) == 1
    assert rec.results[0].result == "PASS", (
        f"pre-cutoff event 500 should suppress under cutoff 1000, got "
        f"{rec.results[0].result}: {rec.results[0].detail}"
    )


def test_cutoff_does_not_suppress_post_cutoff_event_ids(env, patch_cutoff):
    """At/after-cutoff violations still surface — the cutoff only
    suppresses historical residue, never new findings."""
    conn = env["conn"]
    holder, other = _sid("c"), _sid("d")
    _add_session(conn, holder)
    _add_session(conn, other)
    _add_claim(conn, holder, 901)
    _add_event_with_id(
        conn, target_id=2000, name="YokeFunctionCalled", sid=other,
        item_id=901, context={"function": "items.structured_field.replace"},
    )
    patch_cutoff(1000)
    rec = _run(conn)
    assert len(rec.results) == 1
    assert rec.results[0].result == "FAIL", (
        f"post-cutoff event 2000 should still classify as FAIL under "
        f"cutoff 1000, got {rec.results[0].result}: {rec.results[0].detail}"
    )
    assert "function_call_attribution_mismatch" in rec.results[0].detail
    assert "YOK-901" in rec.results[0].detail


def test_cutoff_zero_means_no_filtering(env, patch_cutoff):
    """Default cutoff of 0 disables the filter so a fresh-install
    project sees the full audit."""
    conn = env["conn"]
    holder, other = _sid("e"), _sid("f")
    _add_session(conn, holder)
    _add_session(conn, other)
    _add_claim(conn, holder, 902)
    _add_event_with_id(
        conn, target_id=10, name="YokeFunctionCalled", sid=other,
        item_id=902, context={"function": "items.structured_field.replace"},
    )
    patch_cutoff(0)
    rec = _run(conn)
    assert rec.results[0].result == "FAIL"


def test_correlated_harness_preview_does_not_warn(env, patch_cutoff):
    conn = env["conn"]
    sid = _sid("g")
    _add_session(conn, sid)
    _add_claim(conn, sid, 903)
    _add_event_with_id(
        conn, target_id=10, name="YokeFunctionCalled", sid=sid,
        item_id=903, context={"function": "lifecycle.transition.execute"},
    )
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_name": "HarnessToolCallCompleted",
        "session_id": sid,
        "context": {"detail": {"tool_response_preview": json.dumps({
            "success": True,
            "function": "lifecycle.transition.execute",
            "result": {"item_id": 903},
        })}},
    }
    conn.execute(
        "INSERT INTO events (id, event_id, source_type, session_id, severity,"
        " event_kind, event_type, event_name, item_id, envelope,"
        " anomaly_flags, tool_name, created_at)"
        " VALUES (11, %s, 'agent', %s, 'INFO', 'system', 'tool_call',"
        " 'HarnessToolCallCompleted', NULL, %s, 'unattributed', 'Bash',"
        " '2026-05-17T12:00:01Z')",
        (envelope["event_id"], sid, json.dumps(envelope)),
    )
    diagnostic_envelope = {
        "event_id": str(uuid.uuid4()),
        "event_name": "HarnessToolCallCompleted",
        "session_id": sid,
        "context": {"detail": {"tool_response_preview": (
            "preview {\"success\": true, \"function\": "
            "\"lifecycle.transition.execute\", \"result\": {\"item_id\": 903}}"
        )}},
    }
    conn.execute(
        "INSERT INTO events (id, event_id, source_type, session_id, severity,"
        " event_kind, event_type, event_name, item_id, envelope,"
        " anomaly_flags, tool_name, created_at)"
        " VALUES (12, %s, 'agent', %s, 'INFO', 'system', 'tool_call',"
        " 'HarnessToolCallCompleted', NULL, %s, 'unattributed', 'Bash',"
        " '2026-05-17T12:00:02Z')",
        (diagnostic_envelope["event_id"], sid, json.dumps(diagnostic_envelope)),
    )
    conn.commit()
    patch_cutoff(0)
    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_apply_event_id_cutoff_helper_skips_when_cutoff_zero():
    where, params = _cutoff.apply_event_id_cutoff(
        "event_name=%s", ["x"], cutoff=0, marker="%s",
    )
    assert where == "event_name=%s"
    assert params == ["x"]


def test_apply_event_id_cutoff_helper_appends_clause():
    where, params = _cutoff.apply_event_id_cutoff(
        "event_name=%s", ["x"], cutoff=500, marker="%s",
    )
    assert where == "event_name=%s AND events.id >= %s"
    assert params == ["x", 500]
