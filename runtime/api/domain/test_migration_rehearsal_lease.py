"""Coverage for the migration-territory lease taken by rehearsal.

The lease is workflow serialization: it stops a second work item authoring a
migration against the same model while one is already mid-flight. That is a
different concern from execution serialization, which the boot applier's
per-database advisory lock owns, so the two never substitute for each other.
"""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally re-exported.

from __future__ import annotations

import pytest

from yoke_core.domain.coordination_leases import LeaseHeldError, active_lease
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.migration_apply_contract import LEASE_KEY_PREFIX
from yoke_core.domain.migration_apply_rehearse import rehearse
from runtime.api.domain.migration_apply_test_helpers import (  # noqa: F401 — fixtures
    _seed_apply_item,
    apply_env,
)
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401 — reused fixtures

LEASE_KEY = f"{LEASE_KEY_PREFIX}primary"


def _held(control_db: str):
    conn = connect(control_db)
    try:
        return active_lease(conn, "yoke", LEASE_KEY)
    finally:
        conn.close()


def test_passing_rehearsal_keeps_the_lease(apply_env) -> None:
    # The item now owns migration territory for this model and holds it
    # until the work lands or an operator releases it. That persistence is
    # the point: a momentary mutex would not stop a second item starting.
    _seed_apply_item(apply_env["control_db"], item_id=6001)

    result = rehearse(
        6001,
        session_id="session-a",
        control_db_path=apply_env["control_db"],
        worktree_path=apply_env["worktree"],
    )

    assert result.all_succeeded
    lease = _held(apply_env["control_db"])
    assert lease is not None, "a passing rehearsal must leave the lease held"
    assert lease.session_id == "session-a"
    assert result.lease_id == lease.id


def test_failing_rehearsal_releases_the_lease(apply_env) -> None:
    # A rehearsal that failed never entered migration territory, so it must
    # not leave the door locked behind it.
    _seed_apply_item(
        apply_env["control_db"], item_id=6002, modules=["nonexistent_module"],
    )

    result = rehearse(
        6002,
        session_id="session-a",
        control_db_path=apply_env["control_db"],
        worktree_path=apply_env["worktree"],
    )

    assert not result.all_succeeded
    assert _held(apply_env["control_db"]) is None


def test_same_session_may_rehearse_again(apply_env) -> None:
    # Iterating on a module is the normal case; re-rehearsing must not be
    # refused by the lease this very session is holding.
    _seed_apply_item(apply_env["control_db"], item_id=6003)
    first = rehearse(
        6003,
        session_id="session-a",
        control_db_path=apply_env["control_db"],
        worktree_path=apply_env["worktree"],
    )

    second = rehearse(
        6003,
        session_id="session-a",
        control_db_path=apply_env["control_db"],
        worktree_path=apply_env["worktree"],
    )

    assert second.all_succeeded
    assert second.lease_id == first.lease_id, "the same lease should be reused"


def test_a_second_session_is_refused_and_told_who_holds_it(apply_env) -> None:
    _seed_apply_item(apply_env["control_db"], item_id=6004)
    rehearse(
        6004,
        session_id="session-a",
        control_db_path=apply_env["control_db"],
        worktree_path=apply_env["worktree"],
    )
    _seed_apply_item(apply_env["control_db"], item_id=6005)

    with pytest.raises(LeaseHeldError, match="session-a") as exc:
        rehearse(
            6005,
            session_id="session-b",
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )
    assert "heartbeat age" in str(exc.value)
    assert "yoke coordination-lease release" in str(exc.value)
