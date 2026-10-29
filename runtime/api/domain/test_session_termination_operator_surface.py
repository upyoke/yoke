# ruff: noqa: F811

"""Termination refuses an operator-driven desktop chat and changes nothing."""

import pytest

from runtime.api.domain import test_session_termination as termination_support
from runtime.api.domain.test_session_termination import (
    _add_open_message,
    _add_target_claim,
    _register_operator_and_target,
    _terminate,
)
from runtime.api.test_sessions import conn  # noqa: F401
from yoke_core.domain.sessions import SessionError
from yoke_core.domain.session_termination import OPERATOR_SURFACE_CODE

termination_events = termination_support._termination_schema_and_events


def _target_on(conn, surface: str) -> int:
    _register_operator_and_target(conn)
    conn.execute(
        "UPDATE harness_sessions SET executor_surface=%s WHERE session_id='worker'",
        (surface,),
    )
    conn.commit()
    _add_target_claim(conn)
    _add_open_message(conn)
    return int(
        conn.execute(
            "SELECT id FROM work_claims WHERE session_id='worker'"
        ).fetchone()[0]
    )


@pytest.mark.parametrize(
    "surface", ["codex-desktop", "claude-desktop", "cursor-desktop"]
)
def test_desktop_termination_is_refused_and_writes_nothing(
    conn, surface, termination_events
) -> None:
    claim_id = _target_on(conn, surface)

    with pytest.raises(SessionError) as refused:
        _terminate(conn)

    assert refused.value.code == OPERATOR_SURFACE_CODE
    message = str(refused.value)
    assert f"Its active claim ids: {claim_id}." in message
    assert "yoke claims work release --claim-id N" in message
    session = conn.execute(
        "SELECT ended_at,terminated_at FROM harness_sessions WHERE session_id='worker'"
    ).fetchone()
    assert tuple(session) == (None, None)
    claim = conn.execute(
        "SELECT released_at FROM work_claims WHERE id=%s", (claim_id,)
    ).fetchone()[0]
    assert claim is None
    recipient = conn.execute(
        "SELECT state,cancelled_at FROM session_message_recipients"
    ).fetchone()
    assert tuple(recipient) == ("injected", None)
    reaps = conn.execute("SELECT COUNT(*) FROM session_termination_reaps").fetchone()
    assert reaps[0] == 0
    assert termination_events == []


def test_cli_surface_termination_still_ends_and_queues_reap(
    conn, termination_events
) -> None:
    _target_on(conn, "codex-cli")

    result = _terminate(conn)

    assert result["session"]["terminated_at"]
    assert result["reap_state"] == "pending"
