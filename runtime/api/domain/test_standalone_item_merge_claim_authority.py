"""Standalone merge claim admission keeps one connection-scoped verdict."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_recovery as recovery


def _lookup(*, result, connection: str = "prod-db-admin") -> dict:
    return {
        "caller_session_id": "session-1",
        "connection": connection,
        "function_id": "claims.work.holder_get",
        "response": SimpleNamespace(success=True, result=result, error=None),
    }


def test_bound_holder_authorizes_the_same_session_without_a_second_read(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        recovery,
        "call_dispatcher",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("the authority connection must not repeat the lookup")
        ),
    )
    lookup = _lookup(result={
        "holder": {"item_id": 7, "session_id": "session-1"},
    }, connection="prod")

    with recovery.bind_work_claim_lookup(lookup):
        assert recovery.claim_error(7, "session-1") == ""


def test_missing_holder_field_names_the_connection_and_function(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        recovery,
        "call_dispatcher",
        lambda **_kwargs: SimpleNamespace(success=True, result={}, error=None),
    )
    monkeypatch.setattr(
        recovery, "_active_connection_name", lambda: "prod-db-admin",
    )

    error = recovery.claim_error(7, "session-1")

    assert "prod-db-admin" in error
    assert "claims.work.holder_get" in error
    assert "no live work claim" not in error
    assert recovery.claim_is_missing(error) is False


def test_explicit_empty_holder_is_the_direct_missing_claim_diagnosis() -> None:
    with recovery.bind_work_claim_lookup(_lookup(result={"holder": None})):
        error = recovery.claim_error(7, "session-1")

    assert error.startswith("no live work claim on this item")


def test_bound_holder_for_a_different_item_is_not_authority() -> None:
    lookup = _lookup(result={
        "holder": {"item_id": 8, "session_id": "session-1"},
    })

    with recovery.bind_work_claim_lookup(lookup):
        error = recovery.claim_error(7, "session-1")

    assert "different item" in error
    assert recovery.claim_is_missing(error) is False


def test_absent_landing_preserves_the_current_claim_diagnosis(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        recovery,
        "claim_error",
        lambda *_a, **_k: "no live work claim on this item; acquire one",
    )

    lane, error = recovery.reacquire_landed_claim(
        item_id=7, session_id="session-1", lane=None,
    )

    assert lane is None
    assert error == "no live work claim on this item; acquire one"
    assert "no durable merge receipt" not in error


def test_absent_landing_with_a_live_claim_reports_the_missing_lane(
    monkeypatch,
) -> None:
    monkeypatch.setattr(recovery, "claim_error", lambda *_a, **_k: "")

    lane, error = recovery.reacquire_landed_claim(
        item_id=7, session_id="session-1", lane=None,
    )

    assert lane is None
    assert "no active worktree lane" in error
    assert "no live work claim" not in error


@pytest.mark.parametrize(
    ("initial_claim_error", "expected"),
    [
        ("no live work claim on this item; acquire one", "no live work claim"),
        ("", "no active worktree lane"),
    ],
    ids=["unclaimed", "claimed"],
)
def test_evidence_only_item_without_a_landing_gets_the_direct_diagnosis(
    initial_claim_error: str,
    expected: str,
    monkeypatch,
    capsys,
) -> None:
    item = {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "release",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "worktrees": [],
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(
        merge_cli, "_session_holds_claim", lambda *_a: initial_claim_error,
    )
    monkeypatch.setattr(
        merge_cli.evidence, "closed_out_envelope", lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(recovery, "branch_needs_receipt", lambda *_a: True)
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(
        recovery, "claim_error", lambda *_a, **_k: initial_claim_error,
    )

    exit_code = merge_cli.run([
        "ITEM-1", "--skip-status", "--no-changes", "--session-id", "session-1",
    ])

    assert exit_code == 1
    error = capsys.readouterr().err
    assert expected in error
    assert "no durable merge receipt" not in error
