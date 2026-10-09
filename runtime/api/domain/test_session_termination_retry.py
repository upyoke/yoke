"""Explicit termination retries preserve failed physical reap evidence."""

import json

import pytest

from runtime.api.domain.test_session_termination import (
    _register_operator_and_target,
    _terminate,
)

pytest_plugins = (
    "runtime.api.test_sessions",
    "runtime.api.domain.test_session_termination",
)


@pytest.mark.parametrize("state", ["failed", "unavailable"])
def test_repeat_requeues_unresolved_reap_without_repeating_logical_stop(
    conn, state, _termination_schema_and_events
):
    _register_operator_and_target(conn)
    first = _terminate(conn)
    terminated_at = first["session"]["terminated_at"]
    prior = {"probe_detail": "physical_reap_unresolved"}
    conn.execute(
        "UPDATE session_termination_reaps SET state=%s,result_code='failed',"
        "completed_at=%s,evidence=%s WHERE target_session_id='worker'",
        (state, "2026-08-26T12:00:01Z", json.dumps(prior)),
    )
    second = _terminate(conn, reason="explicit physical retry")
    assert second["reap_state"] == "pending"
    assert second["deduplicated"] is False
    assert second["session"]["terminated_at"] == terminated_at
    row = conn.execute(
        "SELECT completed_at,result_code,evidence FROM session_termination_reaps"
    ).fetchone()
    assert row[0] is None and row[1] is None
    assert json.loads(row[2])["attempts"][0]["evidence"] == prior
    assert len(_termination_schema_and_events) == 1


def test_successful_repeat_preserves_settled_physical_result(conn):
    _register_operator_and_target(conn)
    _terminate(conn)
    conn.execute(
        "UPDATE session_termination_reaps SET state='succeeded',result_code='killed',evidence=%s",
        (json.dumps({"duration_ms": 7}),),
    )
    assert _terminate(conn)["deduplicated"] is True
    row = conn.execute(
        "SELECT state,result_code,evidence FROM session_termination_reaps"
    ).fetchone()
    assert tuple(row) == ("succeeded", "killed", json.dumps({"duration_ms": 7}))
