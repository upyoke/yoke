"""Coverage for the item-terminal path-claim release hook.

Structurally parallel to ``test_path_claims_item_hook.py`` — the
release hook is the normal-completion counterpart to the cancel
hook. Trigger statuses are ``release`` and ``done``;
reason strings are ``item-release`` / ``item-done`` distinct from
``item-cancelled`` / ``item-stopped`` (AC-2 vs AC-3).
"""

from __future__ import annotations

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import (
    activate,
    cancel,
    get_claim,
    register,
)
from yoke_core.domain.path_claims_item_hook_release import (
    release_claims_on_item_terminal,
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


class TestReleaseClaimsOnItemTerminal:
    def test_returns_none_for_non_terminal_status(self, conn):
        for status in (
            "implementing",
            "reviewing-implementation",
            "reviewed-implementation",
            "polishing-implementation",
            "implemented",
            "cancelled",  # cancelled goes through the cancel hook, not release
            "stopped",
        ):
            assert (
                release_claims_on_item_terminal(
                    conn, item_id=1, new_status=status,
                )
                is None
            )

    def test_returns_zero_when_no_claims_attached(self, conn):
        item_id = _seed_item(conn, item_id=15001)
        assert (
            release_claims_on_item_terminal(
                conn, item_id=item_id, new_status="release",
            )
            == 0
        )
        assert (
            release_claims_on_item_terminal(
                conn, item_id=item_id, new_status="done",
            )
            == 0
        )

    def test_releases_planned_blocked_and_active_claims(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=15002)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        # planned
        c_planned = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta], item_id=item_id,
        )
        # active
        c_active = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tb], item_id=item_id,
        )
        activate(conn, claim_id=c_active, base_commit_sha=SNAP)
        # blocked (overlaps active claim)
        c_blocked = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tb], item_id=item_id,
            upstream_claim_id=c_active,
        )
        released = release_claims_on_item_terminal(
            conn, item_id=item_id, new_status="release",
        )
        assert released == 3
        for cid in (c_planned, c_active, c_blocked):
            claim = get_claim(conn, cid)
            assert claim["state"] == "released"
            assert claim["release_reason"] == "item-release"

    def test_done_backstop_uses_item_done_reason(self, conn):
        """AC-1 backstop: done normal-completion releases (does not cancel)."""
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=15003)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        release_claims_on_item_terminal(
            conn, item_id=item_id, new_status="done",
        )
        claim = get_claim(conn, cid)
        assert claim["state"] == "released"
        assert claim["release_reason"] == "item-done"

    def test_skips_already_terminal_claims(self, conn):
        """AC-4: idempotent — already-released stays released; cancelled stays cancelled."""
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=15004)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        tc = seed_target(conn, path_string="src/baz.py")
        c_planned = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta], item_id=item_id,
        )
        c_cancelled = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tb], item_id=item_id,
        )
        c_released = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tc], item_id=item_id,
        )
        cancel(conn, claim_id=c_cancelled, reason="abandoned")
        from yoke_core.domain.path_claims import release as _r
        _r(conn, claim_id=c_released, reason="prior merge")

        released = release_claims_on_item_terminal(
            conn, item_id=item_id, new_status="release",
        )
        # Only the planned claim transitions; the cancelled and the
        # already-released ones do not flip.
        assert released == 1
        assert get_claim(conn, c_planned)["state"] == "released"
        assert get_claim(conn, c_planned)["release_reason"] == "item-release"
        # Cancelled stays cancelled, NOT converted to released.
        assert get_claim(conn, c_cancelled)["state"] == "cancelled"
        # Released stays released, original reason preserved.
        assert get_claim(conn, c_released)["state"] == "released"
        assert get_claim(conn, c_released)["release_reason"] == "prior merge"

    def test_fail_open_when_path_claims_table_missing(self, conn):
        conn.execute("DROP TABLE path_claim_amendments")
        conn.execute("DROP TABLE path_claim_targets")
        conn.execute("DROP TABLE path_claim_overrides")
        conn.execute("DROP TABLE path_claims")
        conn.commit()
        item_id = _seed_item(conn, item_id=15005)
        result = release_claims_on_item_terminal(
            conn, item_id=item_id, new_status="release",
        )
        assert result in (0, None)


class TestItemTerminalReleasePropagation:
    """Item-terminal release must mirror the explicit CLI release path
    by calling :func:`propagate_release_unblock` for each released
    claim. Without it, blocked downstreams are stranded indefinitely."""
    @staticmethod
    def _seed_blocked_claim(conn, *, item_id, target_id, upstream_claim_id):
        cur = conn.execute(
            "INSERT INTO path_claims (state, mode, actor_id, item_id, "
            "integration_target, registered_at, blocked_reason) "
            "VALUES ('blocked', 'exclusive', %s, %s, 'main', "
            "'2026-05-01T00:00:00Z', %s) RETURNING id",
            (local_human(conn), item_id,
             f"serial-via-dependency on path_claims.id={upstream_claim_id}"),
        )
        cid = int(cur.fetchone()[0])
        conn.execute(
            "INSERT INTO path_claim_targets "
            "(claim_id, target_id, declared_at) "
            "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
            (cid, target_id),
        )
        conn.commit()
        return cid

    def test_terminal_hook_unblocks_downstream(self, conn):
        """AC-2: terminal-hook release flips downstream blocked → planned."""
        actor = local_human(conn)
        upstream_item = _seed_item(conn, item_id=16001)
        downstream_item = _seed_item(conn, item_id=16002)
        target = seed_target(conn, path_string="src/foo.py")
        upstream_claim = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=upstream_item,
        )
        activate(conn, claim_id=upstream_claim, base_commit_sha=SNAP)
        downstream_claim = self._seed_blocked_claim(
            conn, item_id=downstream_item, target_id=target,
            upstream_claim_id=upstream_claim,
        )

        release_claims_on_item_terminal(
            conn, item_id=upstream_item, new_status="done",
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
        """Raw-SQL active-claim insert — bypasses overlap classifier so
        sibling claims can share a door lock for AC-3 setup."""
        cur = conn.execute(
            "INSERT INTO path_claims (state, mode, actor_id, item_id, "
            "integration_target, registered_at, activated_at, "
            "base_commit_sha) VALUES ('active', 'exclusive', %s, %s, "
            "'main', '2026-05-01T00:00:00Z', '2026-05-01T01:00:00Z', %s) "
            "RETURNING id",
            (local_human(conn), item_id, SNAP),
        )
        cid = int(cur.fetchone()[0])
        conn.execute(
            "INSERT INTO path_claim_targets "
            "(claim_id, target_id, declared_at) "
            "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
            (cid, target_id),
        )
        conn.commit()
        return cid

    def test_surviving_overlap_keeps_downstream_blocked(self, conn):
        """AC-3: an unrelated active claim still holding the door lock
        keeps the downstream blocked after the upstream releases."""
        upstream_item = _seed_item(conn, item_id=16101)
        sibling_item = _seed_item(conn, item_id=16102)
        downstream_item = _seed_item(conn, item_id=16103)
        target = seed_target(conn, path_string="src/foo.py")
        upstream_claim = self._seed_active_claim(
            conn, item_id=upstream_item, target_id=target,
        )
        # Sibling active claim still holds the door lock after release.
        self._seed_active_claim(
            conn, item_id=sibling_item, target_id=target,
        )
        downstream_claim = self._seed_blocked_claim(
            conn, item_id=downstream_item, target_id=target,
            upstream_claim_id=upstream_claim,
        )

        release_claims_on_item_terminal(
            conn, item_id=upstream_item, new_status="done",
        )

        downstream_after = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s",
            (downstream_claim,),
        ).fetchone()
        assert downstream_after["state"] == "blocked"

    def test_propagation_failure_does_not_abort_remaining_releases(
        self, conn, monkeypatch,
    ):
        """AC-9: one propagation failure must not roll back the claim
        release or prevent later claims from being released."""
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=16201)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        c_first = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[ta], item_id=item_id,
        )
        c_second = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tb], item_id=item_id,
        )

        from yoke_core.domain import (
            path_claims_dependency_propagation as _prop,
        )

        def _explode(*_a, **_kw):
            raise RuntimeError("simulated propagation failure")

        monkeypatch.setattr(_prop, "propagate_release_unblock", _explode)
        released = release_claims_on_item_terminal(
            conn, item_id=item_id, new_status="done",
        )
        assert released == 2
        for cid in (c_first, c_second):
            assert get_claim(conn, cid)["state"] == "released"


class TestBacklogUpdateOpWiring:
    """AC-16: assert release-hook is wired into backlog_update_op for
    release+done transitions, structurally parallel to the cancel hook."""

    def test_release_hook_imported_and_called_for_release_and_done(self):
        import yoke_core.domain.backlog_update_op as bup
        import inspect

        src = inspect.getsource(bup)
        # Hook module is imported in the chokepoint
        assert "path_claims_item_hook_release" in src, (
            "release hook module is not imported in backlog_update_op"
        )
        assert "release_claims_on_item_terminal" in src, (
            "release_claims_on_item_terminal is not referenced in "
            "backlog_update_op"
        )
        # Both terminal triggers route through the chokepoint
        for trigger in ("release", "done"):
            assert f'"{trigger}"' in src, (
                f"backlog_update_op chokepoint does not branch on "
                f"status={trigger!r}"
            )
        assert "done-transition" in src
        assert "deploy-pipeline:" in src

    def test_release_and_cancel_hooks_are_structurally_parallel(self):
        """Both hooks live in the same status-write chokepoint and use
        the same fail-open pattern (try/import-and-call/Exception pass)."""
        import yoke_core.domain.backlog_update_op as bup
        import inspect

        src = inspect.getsource(bup)
        # Cancel hook still wired
        assert "cancel_claims_on_item_terminal" in src
        assert "path_claims_item_hook " in src or "path_claims_item_hook\n" in src
        # Both reasons for release vs cancel are distinct values in the source
        # (the hook modules themselves own the reason strings; this is the
        # entry-trigger verification)
        for status in ("cancelled", "stopped", "release", "done"):
            assert f'"{status}"' in src
