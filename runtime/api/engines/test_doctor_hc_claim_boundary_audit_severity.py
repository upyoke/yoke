"""Mixed severity verdicts for claim-boundary audit findings."""

from runtime.api.engines.test_doctor_hc_claim_boundary_audit import (
    _add_claim,
    _add_event,
    _add_session,
    _run,
    _sid,
    _disable_event_id_cutoff as _disable_event_id_cutoff,
    env as env,
)


def test_fail_severity_dominates_when_mixed(env):
    conn = env["conn"]
    a, b = _sid("7"), _sid("8")
    _add_session(conn, a)
    _add_session(conn, b)
    _add_claim(conn, a, 910, claimed_at="2026-05-17T11:00:00Z")
    _add_event(
        conn,
        "YokeFunctionCalled",
        b,
        910,
        {"function": "items.structured_field.replace"},
    )
    _add_event(
        conn,
        "YokeFunctionCalled",
        b,
        911,
        {"function": "items.section.upsert"},
        created_at="2026-05-17T12:01:00Z",
    )
    rec = _run(conn)
    result = rec.results[0]
    assert result.result == "FAIL"
    assert "1 FAIL" in result.detail
    assert "1 WARN" in result.detail
