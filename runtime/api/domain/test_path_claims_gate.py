"""Tests for the path-claim activation gate at the worktree-create surface.

Slice 10 wires the gate so consumers (worktree-create,
scheduler) cannot open a write surface against an item whose path
claim has not yet activated.
"""

from __future__ import annotations

import pytest

from yoke_core.domain._path_claims_test_helpers import (
    SNAP,
    conn,  # noqa: F401  (pytest fixture)
    local_human,
    seed_target,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.path_claims import (
    activate,
    cancel,
    register,
    release,
)
from yoke_core.domain.path_claims_gate import (
    PathClaimGateBlocked,
    check_worktree_create_gate,
    gate_state_for_item,
)


class TestGateStateForItem:
    def test_no_claims_means_clear_gate(self, conn):
        assert gate_state_for_item(conn, 999) == []

    def test_all_active_means_clear_gate(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=42,
        )
        activate(conn, claim_id=claim_id, base_commit_sha=SNAP)
        assert gate_state_for_item(conn, 42) == []

    def test_all_terminal_means_clear_gate(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=42,
        )
        activate(conn, claim_id=claim_id, base_commit_sha=SNAP)
        release(conn, claim_id=claim_id, reason="merged")
        assert gate_state_for_item(conn, 42) == []

    def test_planned_claim_blocks_gate(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=42,
        )
        assert gate_state_for_item(conn, 42) == [(claim_id, "planned")]

    def test_blocked_claim_blocks_gate(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        upstream = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        downstream = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            upstream_claim_id=upstream,
            item_id=42,
        )
        assert gate_state_for_item(conn, 42) == [(downstream, "blocked")]


class TestCheckWorktreeCreateGate:
    def test_clear_gate_silent(self, conn):
        # No claims for the item → no exception.
        check_worktree_create_gate(conn, 999)

    def test_planned_claim_raises(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=42,
        )
        with pytest.raises(PathClaimGateBlocked, match="state=planned"):
            check_worktree_create_gate(conn, 42)

    def test_active_then_release_clears_gate(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=42,
        )
        activate(conn, claim_id=claim_id, base_commit_sha=SNAP)
        check_worktree_create_gate(conn, 42)
        release(conn, claim_id=claim_id, reason="merged")
        check_worktree_create_gate(conn, 42)

    def test_cancel_clears_gate(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=42,
        )
        cancel(conn, claim_id=claim_id, reason="abandoned")
        check_worktree_create_gate(conn, 42)


def _apply_core_only_schema() -> None:
    """``init_test_db`` strategy building a DB *without* the path tables.

    Simulates the minimal-fixture / freshly-cloned-without-init checkout
    the gate's fail-open branch exists for: core + events tables present,
    ``path_claims`` absent. Resolves its connection through the backend
    factory so the table is genuinely missing on whichever engine runs,
    making the production ``operational_error_types`` swallow fire with the
    matching error type (``sqlite3.OperationalError`` / psycopg
    ``UndefinedTable``) instead of pinning the SQLite-only type.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.events_schema import _create_events_table
    from yoke_core.domain.schema_init_tables import create_core_tables

    c = db_backend.connect()
    try:
        create_core_tables(c)
        _create_events_table(c)
        c.commit()
    finally:
        c.close()


class TestGateMissingTable:
    def test_silent_when_path_claims_absent(self, tmp_path):
        """Minimal fixture / freshly-cloned-without-init checkouts may
        not carry the path_claims table yet. The gate should fail open
        rather than aborting tooling."""
        with init_test_db(tmp_path, apply_schema=_apply_core_only_schema) as db_path:
            c = connect_test_db(db_path)
            try:
                assert gate_state_for_item(c, 42) is None
                # check_worktree_create_gate also tolerates the missing table.
                check_worktree_create_gate(c, 42)
            finally:
                c.close()
