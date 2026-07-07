"""Coverage for the item-terminal path-claim cancellation hook."""

from __future__ import annotations

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import (
    activate,
    get_claim,
    register,
    release,
)
from yoke_core.domain.path_claims_item_hook import (
    cancel_claims_on_item_terminal,
)


def _seed_item(conn, *, item_id: int):
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 't', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


class TestCancelClaimsOnItemTerminal:
    def test_returns_none_for_non_terminal_status(self, conn):
        result = cancel_claims_on_item_terminal(
            conn, item_id=1, new_status="implementing",
        )
        assert result is None

    def test_returns_zero_when_no_claims_attached(self, conn):
        item_id = _seed_item(conn, item_id=14001)
        assert cancel_claims_on_item_terminal(
            conn, item_id=item_id, new_status="cancelled",
        ) == 0

    def test_cancels_planned_blocked_and_active_claims(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=14002)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        # planned
        c1 = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta], item_id=item_id,
        )
        # active
        c2 = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tb], item_id=item_id,
        )
        activate(conn, claim_id=c2, base_commit_sha=SNAP)
        # blocked (overlaps active claim)
        c3 = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tb], item_id=item_id,
            upstream_claim_id=c2,
        )
        cancelled = cancel_claims_on_item_terminal(
            conn, item_id=item_id, new_status="cancelled",
        )
        assert cancelled == 3
        for cid in (c1, c2, c3):
            claim = get_claim(conn, cid)
            assert claim["state"] == "cancelled"
            assert claim["cancel_reason"] == "item-cancelled"

    def test_uses_item_stopped_reason_for_stopped_status(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=14003)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        cancel_claims_on_item_terminal(
            conn, item_id=item_id, new_status="stopped",
        )
        claim = get_claim(conn, cid)
        assert claim["state"] == "cancelled"
        assert claim["cancel_reason"] == "item-stopped"

    def test_skips_already_terminal_claims(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=14004)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        c_active = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta], item_id=item_id,
        )
        c_planned = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tb], item_id=item_id,
        )
        # Release c_active first — should not be re-cancelled
        activate(conn, claim_id=c_active, base_commit_sha=SNAP)
        release(conn, claim_id=c_active, reason="merged")
        cancelled = cancel_claims_on_item_terminal(
            conn, item_id=item_id, new_status="cancelled",
        )
        assert cancelled == 1  # only the planned claim
        assert get_claim(conn, c_active)["state"] == "released"
        assert get_claim(conn, c_planned)["state"] == "cancelled"

    def test_fail_open_when_path_claims_table_missing(self, conn):
        conn.execute("DROP TABLE path_claim_amendments")
        conn.execute("DROP TABLE path_claim_targets")
        # path_claim_overrides FKs into path_claims; the whole claim family
        # is what this test simulates as absent.
        conn.execute("DROP TABLE path_claim_overrides")
        conn.execute("DROP TABLE path_claims")
        conn.commit()
        item_id = _seed_item(conn, item_id=14005)
        # Should return 0 (nothing to cancel) without raising
        result = cancel_claims_on_item_terminal(
            conn, item_id=item_id, new_status="cancelled",
        )
        assert result in (0, None)
