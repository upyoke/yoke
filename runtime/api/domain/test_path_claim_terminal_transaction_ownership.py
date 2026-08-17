"""Caller-owned terminal hooks must abort instead of hiding claim failures."""

# ruff: noqa: F811

from __future__ import annotations

import pytest

from yoke_core.domain import path_claims
from runtime.api.domain._path_claims_test_helpers import (
    conn,  # noqa: F401  (pytest fixture)
    local_human,
    seed_item,
    seed_target,
)
from yoke_core.domain.path_claims import IllegalTransition, register
from yoke_core.domain.path_claims_item_hook import (
    cancel_claims_on_item_terminal,
)
from yoke_core.domain.path_claims_item_hook_release import (
    release_claims_on_item_terminal,
)


def _planned_item_claim(conn) -> int:
    seed_item(conn, item_id=72)
    target_id = seed_target(conn, path_string="src/terminal-ownership.py")
    return register(
        conn,
        actor_id=local_human(conn),
        integration_target="main",
        target_ids=[target_id],
        item_id=72,
    )


def test_cancel_hook_propagates_failure_in_caller_transaction(
    conn,
    monkeypatch,
) -> None:
    _planned_item_claim(conn)

    def fail(*_args, **_kwargs):
        raise IllegalTransition("concurrent terminal state")

    monkeypatch.setattr(path_claims, "cancel", fail)
    with pytest.raises(IllegalTransition, match="concurrent terminal state"):
        cancel_claims_on_item_terminal(
            conn,
            item_id=72,
            new_status="cancelled",
            commit=False,
        )


def test_release_hook_propagates_failure_in_caller_transaction(
    conn,
    monkeypatch,
) -> None:
    _planned_item_claim(conn)

    def fail(*_args, **_kwargs):
        raise IllegalTransition("concurrent terminal state")

    monkeypatch.setattr(path_claims, "release", fail)
    with pytest.raises(IllegalTransition, match="concurrent terminal state"):
        release_claims_on_item_terminal(
            conn,
            item_id=72,
            new_status="done",
            terminal_statuses={"done"},
            propagate=False,
            commit=False,
        )
