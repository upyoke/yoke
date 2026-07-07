"""Done-item residue classification for HC-claim-boundary-audit."""

from __future__ import annotations

from typing import Any

from runtime.api.engines.test_doctor_hc_claim_boundary_audit import (
    _add_claim,
    _add_event,
    _add_session,
    _p,
    _run,
    _sid,
    env,
)


def _add_item(conn: Any, item_id: int, status: str) -> None:
    p = _p(conn)
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, project_id,"
        " project_sequence, created_at, updated_at)"
        f" VALUES ({p}, {p}, 'issue', {p}, 'medium', 1, {p}, {p}, {p})",
        (
            item_id, f"YOK-{item_id}", status, item_id,
            "2026-05-17T10:00:00Z", "2026-05-17T10:00:00Z",
        ),
    )
    conn.commit()


def test_done_item_no_live_claim_renders_as_historical_residue(env):
    conn = env["conn"]
    caller = _sid("r")
    _add_item(conn, 915, "done")
    _add_session(conn, caller)
    _add_event(
        conn, "YokeFunctionCalled", caller, 915,
        {"function": "items.progress_log.append"},
    )

    result = _run(conn).results[0]

    assert result.result == "WARN"
    assert "historical_done_item_residue" in result.detail
    assert "no live work claim" in result.detail
    assert "YOK-915" in result.detail


def test_done_item_live_holder_mismatch_remains_failure(env):
    conn = env["conn"]
    holder, other = _sid("s"), _sid("t")
    _add_item(conn, 916, "done")
    _add_session(conn, holder)
    _add_session(conn, other)
    _add_claim(conn, holder, 916)
    _add_event(
        conn, "YokeFunctionCalled", other, 916,
        {"function": "items.progress_log.append"},
    )

    result = _run(conn).results[0]

    assert result.result == "FAIL"
    assert "historical_done_item_residue" not in result.detail
    assert holder in result.detail and other in result.detail


def test_qa_requirement_list_is_not_mutation(env):
    conn = env["conn"]
    caller = _sid("u")
    _add_session(conn, caller)
    _add_event(
        conn, "YokeFunctionCalled", caller, 917,
        {"function": "qa.requirement.list"},
    )

    assert _run(conn).results[0].result == "PASS"
