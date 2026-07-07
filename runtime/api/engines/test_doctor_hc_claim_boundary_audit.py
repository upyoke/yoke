"""Integration tests for the claim-boundary audit Doctor HC.

Covers PASS, WARN-only, and FAIL outcomes for each finding class plus
the minimal-schema self-skip path.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Iterator

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import check_claim_boundary_audit_cutoff as _cutoff
from yoke_core.engines.doctor_hc_claim_boundary_audit import (
    hc_claim_boundary_audit,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@pytest.fixture(autouse=True)
def _disable_event_id_cutoff(monkeypatch: pytest.MonkeyPatch):
    """Classifier-focused tests author synthetic events that auto-
    increment from id=1; the canonical residue cutoff would suppress
    them. The cutoff sibling module owns its own coverage in
    ``test_doctor_hc_claim_boundary_audit_cutoff``."""
    monkeypatch.setattr(_cutoff, "read_min_event_id_cutoff", lambda: 0)
    yield


def _add_event(
    conn, name: str, sid: str,
    item_id: int | None, context: dict,
    created_at: str = "2026-05-17T12:00:00Z",
) -> int:
    p = _p(conn)
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_name": name,
        "session_id": sid,
        "context": context,
    }
    cur = conn.execute(
        "INSERT INTO events (event_id, source_type, session_id, severity,"
        " event_kind, event_type, event_name, item_id, envelope, created_at)"
        f" VALUES ({p}, 'backend', {p}, 'INFO', 'lifecycle', 'function_call',"
        f" {p}, {p}, {p}, {p}) RETURNING id",
        (envelope["event_id"], sid, name,
         str(item_id) if item_id is not None else None,
         json.dumps(envelope), created_at),
    )
    conn.commit()
    return int(cur.fetchone()[0])


def _add_session(conn, sid: str) -> None:
    p = _p(conn)
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model,"
        " workspace, mode, offered_at, last_heartbeat)"
        f" VALUES ({p}, 'claude-desktop', 'anthropic', 'claude-opus-4-7',"
        " '/tmp/ws', 'charge', '2026-05-17T11:00:00Z',"
        " '2026-05-17T11:00:00Z')",
        (sid,),
    )
    conn.commit()


def _add_claim(
    conn, sid: str, item_id: int,
    claimed_at: str = "2026-05-17T11:30:00Z",
    released_at: str | None = None,
) -> None:
    p = _p(conn)
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id,"
        " claimed_at, last_heartbeat, released_at)"
        f" VALUES ({p}, 'item', {p}, {p}, {p}, {p})",
        (sid, item_id, claimed_at, claimed_at, released_at),
    )
    conn.commit()


def _sid(label: str) -> str:
    return f"{label * 8}-{label * 4}-{label * 4}-{label * 4}-{label * 12}"


@pytest.fixture
def env(tmp_path: Path) -> Iterator[dict]:
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield {"conn": conn}
        finally:
            conn.close()


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_claim_boundary_audit(conn, DoctorArgs(), rec)
    return rec


def test_self_skip_on_minimal_schema():
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    try:
        rec = _run(conn)
    finally:
        conn.close()
    assert len(rec.results) == 1
    assert rec.results[0].result == "PASS"
    assert "skipping" in rec.results[0].detail


def test_pass_when_no_relevant_events(env):
    rec = _run(env["conn"])
    assert len(rec.results) == 1
    assert rec.results[0].result == "PASS"


def test_function_call_fail_when_caller_not_holder(env):
    conn = env["conn"]
    holder, other = _sid("a"), _sid("b")
    _add_session(conn, holder)
    _add_session(conn, other)
    _add_claim(conn, holder, 900)
    _add_event(
        conn, "YokeFunctionCalled", other, 900,
        {"function": "items.structured_field.replace"},
    )
    rec = _run(conn)
    result = rec.results[0]
    assert result.result == "FAIL"
    assert "function_call_attribution_mismatch" in result.detail
    assert "YOK-900" in result.detail
    assert holder in result.detail and other in result.detail
    assert "items.structured_field.replace" in result.detail


def test_function_call_warn_when_no_live_claim(env):
    conn = env["conn"]
    caller = _sid("c")
    _add_session(conn, caller)
    _add_event(
        conn, "YokeFunctionCalled", caller, 901,
        {"function": "items.section.upsert"},
    )
    rec = _run(conn)
    result = rec.results[0]
    assert result.result == "WARN"
    assert "no live work claim" in result.detail
    assert "YOK-901" in result.detail


def test_function_call_warns_on_unattributed_harness_pair_shape(env):
    """Fixture for live events 1590131 / 1590087: ambient harness row
    has the caller, paired YokeFunctionCalled row has holder-shaped
    attribution, and the audit must not report a false PASS."""
    conn = env["conn"]
    holder, caller = _sid("h"), _sid("i")
    _add_session(conn, holder)
    _add_session(conn, caller)
    _add_claim(conn, holder, 912, claimed_at="2026-05-17T11:00:00Z")
    _add_event(
        conn, "YokeFunctionCalled", holder, 912,
        {"function": "items.structured_field.replace"},
    )
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_name": "HarnessToolCallCompleted",
        "session_id": caller,
        "context": {"detail": {
            "tool_response_preview": (
                '{"success": true, "function": '
                '"items.structured_field.replace", "result": '
                '{"item_id": 912}}'
            )
        }},
    }
    p = _p(conn)
    conn.execute(
        "INSERT INTO events (event_id, source_type, session_id, severity,"
        " event_kind, event_type, event_name, item_id, envelope,"
        " anomaly_flags, tool_name, created_at)"
        f" VALUES ({p}, 'agent', {p}, 'INFO', 'system', 'tool_call',"
        f" 'HarnessToolCallCompleted', NULL, {p}, 'unattributed', 'Bash',"
        " '2026-05-17T12:00:01Z')",
        (envelope["event_id"], caller, json.dumps(envelope)),
    )
    conn.commit()
    rec = _run(conn)
    result = rec.results[0]
    assert result.result == "WARN"
    assert "attribution is not correlated" in result.detail
    assert "YOK-912" in result.detail


def test_function_call_pass_when_caller_is_holder(env):
    conn = env["conn"]
    sid = _sid("d")
    _add_session(conn, sid)
    _add_claim(conn, sid, 902, claimed_at="2026-05-17T11:00:00Z")
    _add_event(
        conn, "YokeFunctionCalled", sid, 902,
        {"function": "items.structured_field.replace"},
    )
    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_function_call_ignores_read_functions(env):
    conn = env["conn"]
    sid = _sid("e")
    _add_session(conn, sid)
    _add_event(
        conn, "YokeFunctionCalled", sid, 903,
        {"function": "items.body.read"},
    )
    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_release_override_warn_missing_operator_rationale(env):
    conn = env["conn"]
    sid = _sid("f")
    _add_session(conn, sid)
    _add_event(
        conn, "ItemClaimReleaseOverride", sid, 904,
        {
            "prior_owner_session_id": sid, "claim_id": 99,
            "operator_rationale": "",
        },
    )
    rec = _run(conn)
    result = rec.results[0]
    assert result.result == "WARN"
    assert "operator_rationale" in result.detail
    assert "YOK-904" in result.detail


def test_release_override_fail_on_cross_session(env):
    conn = env["conn"]
    holder, other = _sid("1"), _sid("2")
    _add_session(conn, holder)
    _add_session(conn, other)
    _add_event(
        conn, "ItemClaimReleaseOverride", other, 905,
        {
            "prior_owner_session_id": holder, "claim_id": 100,
            "operator_rationale": "ticket coordination",
        },
    )
    rec = _run(conn)
    result = rec.results[0]
    assert result.result == "FAIL"
    assert "non_operator_claim_release_override" in result.detail
    assert holder in result.detail and other in result.detail


def test_release_override_pass_same_session_with_rationale(env):
    conn = env["conn"]
    sid = _sid("3")
    _add_session(conn, sid)
    _add_event(
        conn, "ItemClaimReleaseOverride", sid, 906,
        {
            "prior_owner_session_id": sid, "claim_id": 101,
            "operator_rationale": "self-release with rationale",
        },
    )
    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_path_claim_amendment_fail_when_caller_not_holder(env):
    conn = env["conn"]
    holder, other = _sid("4"), _sid("5")
    _add_session(conn, holder)
    _add_session(conn, other)
    _add_claim(conn, holder, 907, claimed_at="2026-05-17T11:00:00Z")
    _add_event(
        conn, "PathClaimAmended", other, 907,
        {"claim_id": 50, "amendment_kind": "widen"},
    )
    rec = _run(conn)
    result = rec.results[0]
    assert result.result == "FAIL"
    assert "path_claim_mutation_without_owning_claim" in result.detail
    assert "YOK-907" in result.detail


def test_path_claim_amendment_warn_no_live_claim(env):
    conn = env["conn"]
    sid = _sid("6")
    _add_session(conn, sid)
    _add_event(
        conn, "PathClaimAmended", sid, 908,
        {"claim_id": 51, "amendment_kind": "widen"},
    )
    rec = _run(conn)
    result = rec.results[0]
    assert result.result == "WARN"
    assert "path-claim amendment recorded without" in result.detail


def test_fail_severity_dominates_when_mixed(env):
    conn = env["conn"]
    a, b = _sid("7"), _sid("8")
    _add_session(conn, a)
    _add_session(conn, b)
    _add_claim(conn, a, 910, claimed_at="2026-05-17T11:00:00Z")
    _add_event(
        conn, "YokeFunctionCalled", b, 910,
        {"function": "items.structured_field.replace"},
    )
    _add_event(
        conn, "YokeFunctionCalled", b, 911,
        {"function": "items.section.upsert"},
        created_at="2026-05-17T12:01:00Z",
    )
    rec = _run(conn)
    result = rec.results[0]
    assert result.result == "FAIL"
    assert "1 FAIL" in result.detail
    assert "1 WARN" in result.detail
