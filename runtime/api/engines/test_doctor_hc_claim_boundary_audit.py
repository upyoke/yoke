"""Integration tests for the claim-boundary audit Doctor HC.

Covers PASS, WARN-only, and FAIL outcomes for each finding class plus
the minimal-schema self-skip path.
"""

from __future__ import annotations

from runtime.api.engines.doctor_hc_claim_boundary_audit_test_support import (_add_claim as _add_claim, _add_event as _add_event, _add_session as _add_session, _disable_event_id_cutoff as _disable_event_id_cutoff, _run as _run, _sid as _sid, env as env)
from runtime.api.domain.path_context_test_support import (_p as _p)


import json
import uuid


from runtime.api.fixtures import pg_testdb


def test_self_skip_on_minimal_schema():
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(pg_testdb.connect_test_database(name), name)
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
        conn,
        "YokeFunctionCalled",
        other,
        900,
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
        conn, "YokeFunctionCalled", caller, 901, {"function": "items.section.upsert"}
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
        conn,
        "YokeFunctionCalled",
        holder,
        912,
        {"function": "items.structured_field.replace"},
    )
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_name": "HarnessToolCallCompleted",
        "session_id": caller,
        "context": {
            "detail": {
                "tool_response_preview": (
                    '{"success": true, "function": "items.structured_field.replace", "result": {"item_id": 912}}'
                )
            }
        },
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
        conn,
        "YokeFunctionCalled",
        sid,
        902,
        {"function": "items.structured_field.replace"},
    )
    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_function_call_ignores_read_functions(env):
    conn = env["conn"]
    sid = _sid("e")
    _add_session(conn, sid)
    _add_event(conn, "YokeFunctionCalled", sid, 903, {"function": "items.body.read"})
    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_release_override_warn_missing_operator_rationale(env):
    conn = env["conn"]
    sid = _sid("f")
    _add_session(conn, sid)
    _add_event(
        conn,
        "ItemClaimReleaseOverride",
        sid,
        904,
        {"prior_owner_session_id": sid, "claim_id": 99, "operator_rationale": ""},
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
        conn,
        "ItemClaimReleaseOverride",
        other,
        905,
        {
            "prior_owner_session_id": holder,
            "claim_id": 100,
            "operator_rationale": "work-item coordination",
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
        conn,
        "ItemClaimReleaseOverride",
        sid,
        906,
        {
            "prior_owner_session_id": sid,
            "claim_id": 101,
            "operator_rationale": "self-release with rationale",
        },
    )
    rec = _run(conn)
    assert rec.results[0].result == "PASS"
