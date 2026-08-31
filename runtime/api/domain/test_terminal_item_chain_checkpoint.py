"""Terminal item closeout consumes only the checkpoint for that item."""

from __future__ import annotations

from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog import insert_item
from runtime.api.test_sessions import _register
from yoke_core.domain import backlog, backlog_update_op
from yoke_core.domain.sessions import (
    claim_work,
    end_session_if_empty,
    read_chain_checkpoint,
    update_chain_checkpoint,
)
from yoke_core.domain.sessions_terminal_chain_checkpoint import (
    OUTCOME_TERMINAL_ITEM_CLOSED,
    TERMINAL_ITEM_CLOSED_LABEL,
)


def _seed_claimed_chain(
    test_db,
    *,
    item_id: int,
    session_id: str,
    checkpoint_item_id: int | str | None = None,
    chainable: bool = True,
) -> None:
    insert_item(test_db, id=item_id, workflow_id="issue", status="release")
    _register(test_db, session_id=session_id)
    claim_work(test_db, session_id=session_id, item_id=item_id)
    update_chain_checkpoint(
        test_db,
        session_id,
        step=1,
        action="resume",
        chainable=chainable,
        handler_outcome="completed",
        item_id=checkpoint_item_id if checkpoint_item_id is not None else item_id,
        status="release",
        required_path="dash",
        pre_status="release",
        chain_summary_label="handler completed",
    )


def _finish_item(test_db, monkeypatch, *, item_id: int, session_id: str) -> None:
    _isolate_status_effects(monkeypatch)
    monkeypatch.setattr(
        backlog_update_op,
        "_run_authoritative_status_gate",
        lambda **_kwargs: None,
    )
    result = backlog.execute_update(
        item_id=item_id,
        field="status",
        value="done",
        done_nonce_verified=True,
        force=True,
        qa_bypass=True,
        no_github=True,
        rebuild_board=False,
        session_id=session_id,
    )
    assert result["success"] is True


def test_terminal_transition_consumes_checkpoint_and_final_hook_ends(
    test_db,
    monkeypatch,
) -> None:
    item_id = 9841
    session_id = "terminal-chain-final-hook"
    _seed_claimed_chain(
        test_db,
        item_id=item_id,
        session_id=session_id,
        checkpoint_item_id="YOK-9841",
    )

    _finish_item(test_db, monkeypatch, item_id=item_id, session_id=session_id)

    checkpoint = read_chain_checkpoint(test_db, session_id)
    assert checkpoint is not None
    assert checkpoint["handler_outcome"] == OUTCOME_TERMINAL_ITEM_CLOSED
    assert checkpoint["chain_summary_label"] == TERMINAL_ITEM_CLOSED_LABEL
    assert checkpoint["chainable"] is True
    assert checkpoint["status"] == "done"
    ended = end_session_if_empty(test_db, session_id)
    assert ended["status"] == "ended"
    assert ended["ended"] is True


def test_post_handler_checkpoint_does_not_reopen_finished_item(
    test_db,
    monkeypatch,
) -> None:
    item_id = 9842
    session_id = "terminal-chain-post-handler"
    _seed_claimed_chain(test_db, item_id=item_id, session_id=session_id)
    _finish_item(test_db, monkeypatch, item_id=item_id, session_id=session_id)

    checkpoint = update_chain_checkpoint(
        test_db,
        session_id,
        step=1,
        action="resume",
        chainable=True,
        handler_outcome="completed",
        item_id=item_id,
        status="done",
        required_path="dash",
        pre_status="release",
        chain_summary_label="handler completed",
    )

    assert checkpoint["handler_outcome"] == OUTCOME_TERMINAL_ITEM_CLOSED
    assert checkpoint["chain_summary_label"] == TERMINAL_ITEM_CLOSED_LABEL
    assert end_session_if_empty(test_db, session_id)["status"] == "ended"


def test_terminal_closeout_preserves_checkpoint_for_other_work(
    test_db,
    monkeypatch,
) -> None:
    item_id = 9843
    next_item_id = 9844
    session_id = "terminal-chain-newer-work"
    insert_item(test_db, id=next_item_id, workflow_id="issue", status="idea")
    _seed_claimed_chain(
        test_db,
        item_id=item_id,
        session_id=session_id,
        checkpoint_item_id=next_item_id,
    )

    _finish_item(test_db, monkeypatch, item_id=item_id, session_id=session_id)

    checkpoint = read_chain_checkpoint(test_db, session_id)
    assert checkpoint is not None
    assert checkpoint["item_id"] == next_item_id
    assert checkpoint["handler_outcome"] == "completed"
    assert end_session_if_empty(test_db, session_id)["status"] == "chain_pending"


def test_live_reoffer_replaces_consumed_checkpoint_with_next_item(
    test_db,
    monkeypatch,
) -> None:
    item_id = 9845
    next_item_id = 9846
    session_id = "terminal-chain-live-reoffer"
    _seed_claimed_chain(test_db, item_id=item_id, session_id=session_id)
    _finish_item(test_db, monkeypatch, item_id=item_id, session_id=session_id)
    insert_item(test_db, id=next_item_id, workflow_id="issue", status="idea")

    checkpoint = update_chain_checkpoint(
        test_db,
        session_id,
        step=2,
        action="charge",
        chainable=True,
        handler_outcome="completed",
        item_id=next_item_id,
        status="idea",
        required_path="refine",
        pre_status="idea",
        chain_summary_label="handler completed",
    )

    assert checkpoint["item_id"] == next_item_id
    assert checkpoint["handler_outcome"] == "completed"
    assert end_session_if_empty(test_db, session_id)["status"] == "chain_pending"
