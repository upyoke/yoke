"""Coverage for path-claim release at a pinned workflow's terminal stages."""

# ruff: noqa: F811

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
        "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 't', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea', 'medium', "
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
                    conn,
                    item_id=1,
                    new_status=status,
                )
                is None
            )

    def test_returns_zero_when_no_claims_attached(self, conn):
        item_id = _seed_item(conn, item_id=15001)
        assert (
            release_claims_on_item_terminal(
                conn,
                item_id=item_id,
                new_status="release",
            )
            == 0
        )
        assert (
            release_claims_on_item_terminal(
                conn,
                item_id=item_id,
                new_status="done",
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
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[ta],
            item_id=item_id,
        )
        # active
        c_active = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[tb],
            item_id=item_id,
        )
        activate(conn, claim_id=c_active, base_commit_sha=SNAP)
        # blocked (overlaps active claim)
        c_blocked = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[tb],
            item_id=item_id,
            upstream_claim_id=c_active,
        )
        released = release_claims_on_item_terminal(
            conn,
            item_id=item_id,
            new_status="release",
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
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=item_id,
        )
        release_claims_on_item_terminal(
            conn,
            item_id=item_id,
            new_status="done",
        )
        claim = get_claim(conn, cid)
        assert claim["state"] == "released"
        assert claim["release_reason"] == "item-done"

    def test_skips_already_terminal_claims(self, conn):
        """Idempotent — already-released stays released; cancelled stays cancelled."""
        actor = local_human(conn)
        item_id = _seed_item(conn, item_id=15004)
        ta = seed_target(conn, path_string="src/foo.py")
        tb = seed_target(conn, path_string="src/bar.py")
        tc = seed_target(conn, path_string="src/baz.py")
        c_planned = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[ta],
            item_id=item_id,
        )
        c_cancelled = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[tb],
            item_id=item_id,
        )
        c_released = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[tc],
            item_id=item_id,
        )
        cancel(conn, claim_id=c_cancelled, reason="abandoned")
        from yoke_core.domain.path_claims import release as _r

        _r(conn, claim_id=c_released, reason="prior merge")

        released = release_claims_on_item_terminal(
            conn,
            item_id=item_id,
            new_status="release",
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
        conn.execute("DROP TABLE path_claim_task_bindings")
        conn.execute("DROP TABLE path_claims")
        conn.commit()
        item_id = _seed_item(conn, item_id=15005)
        result = release_claims_on_item_terminal(
            conn,
            item_id=item_id,
            new_status="release",
        )
        assert result in (0, None)


class TestBacklogUpdateOpWiring:
    """Terminal path-claim hooks share the transactional update effects."""

    def test_release_hook_imported_and_called_for_release_and_done(self):
        import yoke_core.domain.backlog_update_effects as effects
        import inspect

        src = inspect.getsource(effects)
        assert "path_claims_item_hook_release" in src, (
            "release hook module is not imported in update effects"
        )
        assert "release_claims_on_item_terminal" in src, (
            "release_claims_on_item_terminal is not referenced in update effects"
        )
        for trigger in ("release", "done"):
            assert f'"{trigger}"' in src, (
                f"update-effects chokepoint does not branch on status={trigger!r}"
            )
        assert "done-transition" in src
        assert "deploy-pipeline:" in src

    def test_release_and_cancel_hooks_are_structurally_parallel(self):
        """Both hooks run in the same fail-closed status transaction."""
        import yoke_core.domain.backlog_update_effects as effects
        import inspect

        src = inspect.getsource(effects)
        assert "cancel_claims_on_item_terminal" in src
        assert "path_claims_item_hook " in src or "path_claims_item_hook\n" in src
        for status in ("cancelled", "stopped", "release", "done"):
            assert f'"{status}"' in src
        assert "except Exception" not in inspect.getsource(
            effects._clean_terminal_path_claims
        )
