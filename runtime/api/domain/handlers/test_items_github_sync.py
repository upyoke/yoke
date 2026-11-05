"""Tests for the ``items.github_sync`` function handler."""

from __future__ import annotations

from contextlib import nullcontext

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import items_github_sync


@pytest.fixture(autouse=True)
def enabled_project(monkeypatch):
    conn = object()
    monkeypatch.setattr(
        items_github_sync.db_helpers, "connect", lambda: nullcontext(conn)
    )
    monkeypatch.setattr(
        items_github_sync.backlog_github_sync,
        "_item_context",
        lambda raw, **kwargs: ("", "example", "org/repo"),
    )
    monkeypatch.setattr(items_github_sync, "github_sync_enabled", lambda *a, **kw: True)


def _request(item_id: int = 71) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.github_sync",
        actor=ActorContext(session_id="session-A"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={},
    )


def test_github_sync_reuses_allow_unclaimed_guard_and_only_mirrors(monkeypatch):
    sync_calls: list[int] = []
    ownership_calls: list[tuple[int, str | None]] = []

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
    outcome = items_github_sync.handle_github_sync(_request())

    assert outcome.primary_success is True
    assert outcome.error is None
    assert outcome.result_payload == {
        "item_id": 71,
        "exit_code": 0,
        "skipped": False,
    }
    # The guard and the sync entry point must receive the resolved internal
    # id. A stringified id is re-read by the operator-argument parser as a
    # project-local sequence, which resolves a different item.
    assert ownership_calls == [(71, "session-A")]
    assert sync_calls == [71]
    assert outcome.warnings == []


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


def test_github_sync_reports_domain_failure(monkeypatch):
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
    outcome = items_github_sync.handle_github_sync(_request())

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "github_sync_failed"


@pytest.mark.parametrize("done", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_sync_reports_project_mode_without_remote_calls_when_disabled(
    monkeypatch,
    done,
    enabled,
):
    sync_calls = []
    mode_calls = []
    monkeypatch.setattr(
        items_github_sync,
        "check_ownership",
        lambda *a, **kw: (True, "", ""),
    )
    monkeypatch.setattr(
        items_github_sync,
        "github_sync_enabled",
        lambda project, **kw: (mode_calls.append(project), enabled)[1],
    )
    monkeypatch.setattr(
        items_github_sync.backlog_github_sync,
        "sync_item",
        lambda *args: (sync_calls.append(args), 0)[1],
    )
    monkeypatch.setattr(
        items_github_sync.backlog_github_sync,
        "sync_done_item",
        lambda *args: (sync_calls.append(args), 0)[1],
    )
    request = _request()
    if done:
        request.function = "items.github_done_sync"
        request.payload = {"old_status": "release"}
    handler = (
        items_github_sync.handle_github_done_sync
        if done
        else items_github_sync.handle_github_sync
    )
    outcome = handler(request)

    assert outcome.primary_success is True
    assert outcome.error is None
    assert outcome.result_payload["skipped"] is (not enabled)
    assert mode_calls == ["example"]
    if enabled:
        assert sync_calls == ([(71, "release")] if done else [(71,)])
        assert outcome.warnings == []
    else:
        assert sync_calls == []
        warning = outcome.warnings[0]
        assert warning.code == "github_sync_disabled"
        assert warning.step == "github_sync"
        assert "github_sync_mode=disabled" in warning.detail
        assert "project 'example'" in warning.detail
        assert (
            "yoke projects update --slug example --name <Name> --github-sync-mode enabled"
            in warning.detail
        )


def test_sync_missing_item_reports_failure(monkeypatch):
    monkeypatch.setattr(
        items_github_sync,
        "check_ownership",
        lambda *a, **kw: (True, "", ""),
    )
    monkeypatch.setattr(
        items_github_sync.backlog_github_sync,
        "_item_context",
        lambda *a, **kw: None,
    )
    outcome = items_github_sync.handle_github_sync(_request())
    assert outcome.primary_success is False
    assert outcome.error.code == "item_not_found"
