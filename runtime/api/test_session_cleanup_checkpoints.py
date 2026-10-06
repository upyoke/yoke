"""Session cleanup follows current holdings and delivery, not checkpoint budget."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from runtime.api.test_sessions import _insert_claimable_item, _register
from yoke_core.domain.sessions import (
    claim_work,
    end_session,
    end_session_if_empty,
    update_chain_checkpoint,
)

pytest_plugins = ("runtime.api.test_sessions",)


@pytest.mark.parametrize("step", [1, 3])
def test_checkpoint_budget_does_not_keep_claimless_session_alive(conn, step):
    _register(conn, session_id="checkpoint-cleanup")
    update_chain_checkpoint(
        conn,
        "checkpoint-cleanup",
        step=step,
        action="refine",
        chainable=True,
        handler_outcome="completed",
    )
    with patch("yoke_core.domain.sessions_analytics._emit_session_event") as emit:
        result = end_session_if_empty(conn, "checkpoint-cleanup")
    assert result["status"] == "ended"
    assert result["ended"] is True
    assert "next_action" not in result
    assert [call.args[0] for call in emit.call_args_list] == ["HarnessSessionEnded"]


def test_idle_cleanup_preserves_claim_despite_checkpoint_budget(conn):
    _register(conn, session_id="checkpoint-holder")
    _insert_claimable_item(conn, 100)
    claim = claim_work(conn, session_id="checkpoint-holder", item_id=100)
    update_chain_checkpoint(
        conn,
        "checkpoint-holder",
        step=1,
        action="refine",
        chainable=True,
        handler_outcome="completed",
    )
    result = end_session_if_empty(conn, "checkpoint-holder")
    assert result["status"] == "has_claims"
    assert result["ended"] is False
    row = conn.execute(
        "SELECT released_at FROM work_claims WHERE id=%s", (claim["id"],)
    ).fetchone()
    assert row["released_at"] is None


def test_failed_explicit_end_does_not_emit_success(conn):
    _register(conn, session_id="interrupted-end")
    with (
        patch(
            "yoke_core.domain.sessions_render_end.clear_current_item",
            side_effect=RuntimeError("interrupted"),
        ),
        patch("yoke_core.domain.sessions_analytics._emit_session_event") as emit,
    ):
        with pytest.raises(RuntimeError, match="interrupted"):
            end_session(conn, "interrupted-end")
    assert not emit.called
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id=%s",
        ("interrupted-end",),
    ).fetchone()
    assert row["ended_at"] is None
