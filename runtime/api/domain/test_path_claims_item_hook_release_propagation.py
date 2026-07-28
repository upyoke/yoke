# ruff: noqa: F811
"""Downstream propagation triggered by item-terminal claim release."""

from yoke_core.domain._path_claims_test_helpers import (
    SNAP,
    conn,  # noqa: F401
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import activate, get_claim, register
from yoke_core.domain.path_claims_item_hook_release import (
    release_claims_on_item_terminal,
)
from runtime.api.domain.test_path_claims_item_hook_release import _seed_item


class TestItemTerminalReleasePropagation:
    @staticmethod
    def _seed_blocked_claim(conn, *, item_id, target_id, upstream_claim_id):
        cur = conn.execute(
            "INSERT INTO path_claims (state, mode, actor_id, item_id, "
            "integration_target, registered_at, blocked_reason) "
            "VALUES ('blocked', 'exclusive', %s, %s, 'main', "
            "'2026-05-01T00:00:00Z', %s) RETURNING id",
            (
                local_human(conn),
                item_id,
                f"serial-via-dependency on path_claims.id={upstream_claim_id}",
            ),
        )
        claim_id = int(cur.fetchone()[0])
        conn.execute(
            "INSERT INTO path_claim_targets "
            "(claim_id, target_id, declared_at) "
            "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
            (claim_id, target_id),
        )
        conn.commit()
        return claim_id

    def test_terminal_hook_unblocks_downstream(self, conn):
        actor = local_human(conn)
        upstream_item = _seed_item(conn, item_id=16001)
        downstream_item = _seed_item(conn, item_id=16002)
        target = seed_target(conn, path_string="src/foo.py")
        upstream_claim = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=upstream_item,
        )
        activate(conn, claim_id=upstream_claim, base_commit_sha=SNAP)
        downstream_claim = self._seed_blocked_claim(
            conn,
            item_id=downstream_item,
            target_id=target,
            upstream_claim_id=upstream_claim,
        )

        release_claims_on_item_terminal(
            conn,
            item_id=upstream_item,
            new_status="done",
        )

        upstream_after = get_claim(conn, upstream_claim)
        assert upstream_after["state"] == "released"
        assert upstream_after["release_reason"] == "item-done"
        downstream_after = conn.execute(
            "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
            (downstream_claim,),
        ).fetchone()
        assert downstream_after["state"] == "planned"
        assert downstream_after["blocked_reason"] is None

    @staticmethod
    def _seed_active_claim(conn, *, item_id, target_id):
        cur = conn.execute(
            "INSERT INTO path_claims (state, mode, actor_id, item_id, "
            "integration_target, registered_at, activated_at, "
            "base_commit_sha) VALUES ('active', 'exclusive', %s, %s, "
            "'main', '2026-05-01T00:00:00Z', '2026-05-01T01:00:00Z', %s) "
            "RETURNING id",
            (local_human(conn), item_id, SNAP),
        )
        claim_id = int(cur.fetchone()[0])
        conn.execute(
            "INSERT INTO path_claim_targets "
            "(claim_id, target_id, declared_at) "
            "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
            (claim_id, target_id),
        )
        conn.commit()
        return claim_id

    def test_surviving_overlap_keeps_downstream_blocked(self, conn):
        upstream_item = _seed_item(conn, item_id=16101)
        sibling_item = _seed_item(conn, item_id=16102)
        downstream_item = _seed_item(conn, item_id=16103)
        target = seed_target(conn, path_string="src/foo.py")
        upstream_claim = self._seed_active_claim(
            conn,
            item_id=upstream_item,
            target_id=target,
        )
        self._seed_active_claim(
            conn,
            item_id=sibling_item,
            target_id=target,
        )
        downstream_claim = self._seed_blocked_claim(
            conn,
            item_id=downstream_item,
            target_id=target,
            upstream_claim_id=upstream_claim,
        )

        release_claims_on_item_terminal(
            conn,
            item_id=upstream_item,
            new_status="done",
        )

        downstream_after = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s",
            (downstream_claim,),
        ).fetchone()
        assert downstream_after["state"] == "blocked"

    def test_propagation_failure_does_not_abort_remaining_releases(
        self,
        conn,
        monkeypatch,
    ):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=16201)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        c_first = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[ta],
            item_id=item_id,
        )
        c_second = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[tb],
            item_id=item_id,
        )

        from yoke_core.domain import path_claims_dependency_propagation as propagation

        def explode(*_args, **_kwargs):
            raise RuntimeError("simulated propagation failure")

        monkeypatch.setattr(propagation, "propagate_release_unblock", explode)
        released = release_claims_on_item_terminal(
            conn,
            item_id=item_id,
            new_status="done",
        )
        assert released == 2
        for claim_id in (c_first, c_second):
            assert get_claim(conn, claim_id)["state"] == "released"
