"""Full-history Doctor aggregates keep their classification on large ledgers."""

from __future__ import annotations

import json
import time

import pytest

from yoke_core.domain.check_claim_boundary_audit_correlation import (
    extract_function_response,
)
from yoke_core.domain.check_claim_boundary_audit_summary import audit_summary
from yoke_core.domain.yoke_function_dispatch_claim_evidence import (
    CLAIM_VERIFICATION_ALLOWED,
    CLAIM_VERIFICATION_PHASE,
)
from runtime.api.engines.test_doctor_hc_claim_boundary_audit import (
    _add_claim,
    _add_event,
    _add_session,
    _disable_event_id_cutoff as _disable_event_id_cutoff,
    _run,
    _sid,
    env as env,
)


def test_summary_classifies_claim_verification_evidence(env):
    conn = env["conn"]
    holder, caller = _sid("a"), _sid("b")
    _add_session(conn, holder)
    _add_session(conn, caller)
    _add_claim(conn, holder, 950)
    common = {"function": "items.structured_field.replace", "target": {"item_id": 950}}
    snapshots = [
        {},
        {
            "phase": CLAIM_VERIFICATION_PHASE,
            "required_kind": "item",
            "decision": CLAIM_VERIFICATION_ALLOWED,
            "caller_session_id": caller,
            "holder_session_id": caller,
        },
        {
            "phase": CLAIM_VERIFICATION_PHASE,
            "required_kind": "item",
            "decision": CLAIM_VERIFICATION_ALLOWED,
            "caller_session_id": holder,
            "holder_session_id": holder,
        },
        {"phase": CLAIM_VERIFICATION_PHASE, "required_kind": "epic"},
        {
            "phase": CLAIM_VERIFICATION_PHASE,
            "required_kind": "item",
            "decision": "denied",
        },
        {
            "phase": CLAIM_VERIFICATION_PHASE,
            "required_kind": "item",
            "decision": CLAIM_VERIFICATION_ALLOWED,
            "caller_session_id": caller,
        },
    ]
    for snapshot in snapshots:
        _add_event(
            conn,
            "YokeFunctionCalled",
            caller,
            950,
            {**common, "claim_verification": snapshot},
        )
    fails, warns, preview = audit_summary(conn)
    assert (fails, warns) == (2, 3)
    assert len(preview) == 5
    assert {f["rationale"] for f in preview} == {
        "function call recorded under a session that did not hold the work claim at event time",
        "event caller differs from the pre-handler verified caller",
        "pre-handler claim evidence disagrees with function metadata",
        "pre-handler evidence does not record an allowed claim decision",
        "pre-handler evidence is missing the verified claim holder",
    }


def test_large_old_ledger_counts_all_findings_and_bounds_preview(env):
    conn = env["conn"]
    caller = _sid("c")
    _add_session(conn, caller)
    _add_event(
        conn,
        "YokeFunctionCalled",
        caller,
        951,
        {"function": "items.structured_field.replace"},
    )
    envelope = json.dumps({"context": {"function": "items.structured_field.replace"}})
    conn.execute(
        """
        INSERT INTO events (event_id, source_type, session_id, severity, event_kind,
                            event_type, event_name, item_id, envelope, created_at)
        SELECT 'bulk-' || n, 'backend', %s, 'INFO', 'lifecycle', 'function_call',
               'YokeFunctionCalled', '951', %s, '2020-01-01T00:00:00Z'
        FROM generate_series(1, 10000) n
    """,
        (caller, envelope),
    )
    conn.commit()
    started = time.monotonic()
    fails, warns, preview = audit_summary(conn)
    assert time.monotonic() - started < 45
    assert (fails, warns) == (0, 10001)
    assert len(preview) == 10
    assert "10001 WARN" in _run(conn).results[0].detail


def test_large_clean_snapshot_ledger_passes(env):
    conn = env["conn"]
    caller = _sid("d")
    _add_session(conn, caller)
    _add_event(
        conn,
        "YokeFunctionCalled",
        caller,
        952,
        {"function": "items.structured_field.replace", "claim_required_kind": None},
    )
    envelope = json.dumps(
        {
            "context": {
                "function": "items.structured_field.replace",
                "claim_verification": {
                    "phase": CLAIM_VERIFICATION_PHASE,
                    "required_kind": "item",
                    "decision": CLAIM_VERIFICATION_ALLOWED,
                    "caller_session_id": caller,
                    "holder_session_id": caller,
                },
            }
        }
    )
    conn.execute(
        """
        INSERT INTO events (event_id, source_type, session_id, severity, event_kind,
                            event_type, event_name, item_id, envelope, created_at)
        SELECT 'clean-' || n, 'backend', %s, 'INFO', 'lifecycle', 'function_call',
               'YokeFunctionCalled', '952', %s, '2020-01-01T00:00:00Z'
        FROM generate_series(1, 10000) n
    """,
        (caller, envelope),
    )
    conn.commit()
    assert _run(conn).results[0].result == "PASS"


def test_shell_preview_nul_keeps_attribution_and_literal_escapes(env):
    from yoke_core.domain.sql_json import jsonb_text_expr

    conn = env["conn"]
    caller = _sid("e")
    _add_session(conn, caller)
    preview = "file\x00\n" + json.dumps(
        {
            "success": True,
            "function": "items.structured_field.replace",
            "result": {"item_id": 953},
        }
    )
    event_id = _add_event(
        conn,
        "HarnessToolCallCompleted",
        caller,
        953,
        {"detail": {"tool_response_preview": preview}},
    )
    conn.execute(
        "UPDATE events SET anomaly_flags='unattributed' WHERE id=%s", (event_id,)
    )
    conn.commit()
    fails, warns, sample = audit_summary(conn)
    assert (fails, warns) == (0, 1)
    assert sample[0]["id"] == event_id
    for value, expected_value in [
        (r"\u0000", r"\u0000"),
        ("\x00\x00", "\x01\x01"),
        ("\\" + "\x00", "\\" + "\x01"),
    ]:
        row = conn.execute(
            f"WITH raw(value) AS (VALUES (%s)) SELECT {jsonb_text_expr('value')} ->> 'value' FROM raw",
            (json.dumps({"value": value}),),
        ).fetchone()
        assert row[0] == expected_value


def test_preview_with_raw_control_inside_response_stays_unparseable(env):
    conn = env["conn"]
    caller = _sid("f")
    _add_session(conn, caller)
    preview = '{"success":true,"function":"items.structured_field.replace","result":{"item_id":953},"value":"\x00"}'
    event_id = _add_event(
        conn,
        "HarnessToolCallCompleted",
        caller,
        953,
        {"detail": {"tool_response_preview": preview}},
    )
    conn.execute(
        "UPDATE events SET anomaly_flags='unattributed' WHERE id=%s", (event_id,)
    )
    conn.commit()
    assert audit_summary(conn)[:2] == (0, 0)


def test_raw_candidate_filter_keeps_unicode_encoded_functions(env):
    conn = env["conn"]
    caller = _sid("g")
    _add_session(conn, caller)
    event_id = _add_event(
        conn,
        "YokeFunctionCalled",
        caller,
        954,
        {"function": "items.structured_field.replace"},
    )
    envelope = json.dumps({"context": {"function": "items.structured_field.replace"}})
    envelope = envelope.replace("structured_field", r"\u0073tructured_field")
    conn.execute("UPDATE events SET envelope=%s WHERE id=%s", (envelope, event_id))
    conn.commit()
    assert audit_summary(conn)[:2] == (0, 1)


@pytest.mark.parametrize(
    "prefix,indent,encoded",
    [
        ("{broken JSON\n", 2, False),
        ('{"success":false}\n', None, False),
        ("shell output\n", 2, True),
        ("", None, True),
        ('{"success":true,"function":"read.only"}\n', None, False),
    ],
)
def test_preview_summary_matches_first_successful_response(
    env, prefix, indent, encoded
):
    conn = env["conn"]
    caller = _sid("h")
    _add_session(conn, caller)
    response = json.dumps(
        {
            "success": True,
            "function": "items.structured_field.replace",
            "result": {"item_id": 955},
        },
        indent=indent,
    )
    if encoded:
        response = response.replace("structured_field", r"\u0073tructured_field")
    event_id = _add_event(
        conn,
        "HarnessToolCallCompleted",
        caller,
        955,
        {"detail": {"tool_response_preview": prefix + response}},
    )
    conn.execute(
        "UPDATE events SET anomaly_flags='unattributed' WHERE id=%s", (event_id,)
    )
    conn.commit()
    function, subject = extract_function_response(prefix + response)
    expected_count = int(
        function == "items.structured_field.replace" and subject == 955
    )
    assert audit_summary(conn)[:2] == (0, expected_count)
