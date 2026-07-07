"""Tests for the ``items.github_sync`` function handler."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import items_github_sync


def _request(item_id: int = 71) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.github_sync",
        actor=ActorContext(session_id="session-A"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={},
    )


def test_github_sync_reuses_allow_unclaimed_guard_and_rebuilds(monkeypatch):
    sync_calls: list[str] = []
    rebuild_calls: list[bool] = []
    ownership_calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        items_github_sync,
        "check_ownership",
        lambda raw, **kwargs: (
            ownership_calls.append((raw, kwargs.get("session_id"))),
            (True, "no-claim", ""),
        )[1],
    )
    monkeypatch.setattr(
        items_github_sync.backlog_github_sync,
        "sync_item",
        lambda raw: (sync_calls.append(raw), 0)[1],
    )
    monkeypatch.setattr(
        items_github_sync.backlog,
        "_maybe_rebuild_board",
        lambda rebuild_board, **_: rebuild_calls.append(rebuild_board),
    )

    outcome = items_github_sync.handle_github_sync(_request())

    assert outcome.primary_success is True
    assert outcome.error is None
    assert outcome.result_payload == {
        "item_id": 71,
        "exit_code": 0,
        "board_rebuild_requested": True,
    }
    assert ownership_calls == [("71", "session-A")]
    assert sync_calls == ["71"]
    assert rebuild_calls == [True]


def test_github_sync_blocks_when_other_session_holds_claim(monkeypatch):
    sync_calls: list[str] = []

    monkeypatch.setattr(
        items_github_sync,
        "check_ownership",
        lambda raw, **_: (False, "other-holder", "session-B"),
    )
    monkeypatch.setattr(
        items_github_sync.backlog_github_sync,
        "sync_item",
        lambda raw: (sync_calls.append(raw), 0)[1],
    )

    outcome = items_github_sync.handle_github_sync(_request())

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "claim_conflict"
    assert "session-B" in outcome.error.message
    assert sync_calls == []


def test_github_sync_reports_domain_failure_without_board_rebuild(monkeypatch):
    rebuild_calls: list[bool] = []

    monkeypatch.setattr(
        items_github_sync,
        "check_ownership",
        lambda raw, **_: (True, "self-owned", "session-A"),
    )
    monkeypatch.setattr(
        items_github_sync.backlog_github_sync,
        "sync_item",
        lambda raw: 1,
    )
    monkeypatch.setattr(
        items_github_sync.backlog,
        "_maybe_rebuild_board",
        lambda rebuild_board, **_: rebuild_calls.append(rebuild_board),
    )

    outcome = items_github_sync.handle_github_sync(_request())

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "github_sync_failed"
    assert rebuild_calls == []
