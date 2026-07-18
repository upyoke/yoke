"""Coverage for the item-facing path-claim registration on-ramp."""

from __future__ import annotations

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import (
    InvalidActor,
    get_claim,
)
from yoke_core.domain.path_claims_register import (
    DefaultActorUnavailable,
    ItemHasNoProject,
    ItemNotFound,
    register_for_item,
)
from yoke_core.domain.path_claims_resolve import (
    EmptyPathSet,
    UnknownPathTargets,
)

_PROJECT_IDS = {"yoke": 1, "externalwebapp": 2}


def _seed_item(
    conn,
    *,
    item_id: int = 9001,
    project: str = "yoke",
    title: str = "test item",
) -> int:
    project_id = int(project) if str(project).isdigit() else _PROJECT_IDS.get(project, 1)
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, %s, 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', %s, %s)",
        (item_id, title, project_id, item_id),
    )
    conn.commit()
    return item_id


def _seed_session(conn, session_id: str) -> str:
    """Insert a harness_sessions row so a path_claims FK can reference it."""
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model, "
        "project_id, execution_lane, capabilities, workspace, mode, offered_at, "
        "last_heartbeat) "
        "VALUES (%s, 'test', 'test', 'test', 1, 'primary', '[]', '/tmp', 'wait', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
        (session_id,),
    )
    conn.commit()
    return session_id


class TestRegisterForItem:
    def test_registers_with_explicit_actor(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        _seed_session(conn, "sess-abc")
        claim_id = register_for_item(
            conn,
            item_id=item_id,
            integration_target="main",
            paths=["runtime/api/domain"],
            actor_id=actor,
            session_id="sess-abc",
        )
        claim = get_claim(conn, claim_id)
        assert claim["state"] == "planned"
        assert claim["actor_id"] == actor
        assert claim["item_id"] == item_id
        assert claim["session_id"] == "sess-abc"
        assert claim["target_ids"] == [target]
        assert claim["integration_target"] == "main"

    def test_resolves_multiple_paths(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        a = seed_target(conn, path_string="runtime/api/domain")
        b = seed_target(conn, path_string="docs/path-claims.md")
        claim_id = register_for_item(
            conn,
            item_id=item_id,
            integration_target="main",
            paths=["docs/path-claims.md", "runtime/api/domain"],
            actor_id=actor,
        )
        claim = get_claim(conn, claim_id)
        assert sorted(claim["target_ids"]) == sorted([a, b])

    def test_missing_item_raises_item_not_found(self, conn):
        actor = local_human(conn)
        seed_target(conn, path_string="runtime/api/domain")
        with pytest.raises(ItemNotFound, match="424242"):
            register_for_item(
                conn,
                item_id=424242,
                integration_target="main",
                paths=["runtime/api/domain"],
                actor_id=actor,
            )

    def test_unknown_path_raises_resolver_error(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        with pytest.raises(UnknownPathTargets):
            register_for_item(
                conn,
                item_id=item_id,
                integration_target="main",
                paths=["no/such/path"],
                actor_id=actor,
            )

    def test_empty_path_list_raises_empty_path_set(self, conn):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        with pytest.raises(EmptyPathSet):
            register_for_item(
                conn,
                item_id=item_id,
                integration_target="main",
                paths=[],
                actor_id=actor,
            )

    def test_explicit_unknown_actor_rejected(self, conn):
        item_id = _seed_item(conn)
        seed_target(conn, path_string="runtime/api/domain")
        with pytest.raises(InvalidActor):
            register_for_item(
                conn,
                item_id=item_id,
                integration_target="main",
                paths=["runtime/api/domain"],
                actor_id=999_999,
            )

    def test_default_actor_unavailable_when_no_session(self, conn, monkeypatch):
        """When no explicit actor is supplied and no session binds one, fail clearly.

        Actor identity is session/auth-bound; if the explicit → session
        ladder cannot answer, the on-ramp surfaces a
        :class:`DefaultActorUnavailable` rather than silently picking an
        actor.
        """
        item_id = _seed_item(conn)
        seed_target(conn, path_string="runtime/api/domain")

        monkeypatch.setattr(
            "yoke_core.domain.path_claims_actor_resolution._current_session_id",
            lambda: "",
        )
        with pytest.raises(DefaultActorUnavailable):
            register_for_item(
                conn,
                item_id=item_id,
                integration_target="main",
                paths=["runtime/api/domain"],
            )

    def test_register_writes_typed_item_owner(self, conn):
        item_id = _seed_item(conn)
        seed_target(conn, path_string="runtime/api/domain")
        claim_id = register_for_item(
            conn,
            item_id=item_id,
            integration_target="main",
            paths=["runtime/api/domain"],
            actor_id=local_human(conn),
        )
        claim = get_claim(conn, claim_id)
        assert claim["owner_kind"] == "item"
        assert claim["owner_item_id"] == item_id
        assert claim["owner_session_id"] is None
        assert claim["owner_work_claim_id"] is None

    def test_register_with_session_provenance_keeps_item_owner(self, conn):
        # The key contract: a live session that registers an item-owned
        # claim is provenance, not the owner.
        item_id = _seed_item(conn)
        session_id = _seed_session(conn, "live-registrar")
        seed_target(conn, path_string="runtime/api/domain")
        claim_id = register_for_item(
            conn,
            item_id=item_id,
            integration_target="main",
            paths=["runtime/api/domain"],
            actor_id=local_human(conn),
            session_id=session_id,
        )
        claim = get_claim(conn, claim_id)
        assert claim["owner_kind"] == "item"
        assert claim["owner_item_id"] == item_id
        # Owner session is NULL — the registering session is provenance.
        assert claim["owner_session_id"] is None
        # Provenance: the legacy session_id AND new registered_by_session_id
        # both name the registrar.
        assert claim["session_id"] == session_id
        assert claim["registered_by_session_id"] == session_id

    def test_register_populates_registered_by_actor(self, conn):
        item_id = _seed_item(conn)
        actor_id = local_human(conn)
        seed_target(conn, path_string="runtime/api/domain")
        claim_id = register_for_item(
            conn,
            item_id=item_id,
            integration_target="main",
            paths=["runtime/api/domain"],
            actor_id=actor_id,
        )
        claim = get_claim(conn, claim_id)
        assert claim["registered_by_actor_id"] == actor_id
        assert claim["actor_id"] == actor_id

    def test_item_with_null_project_rejected(self, conn):
        # Emulate a partial migration corner case where the item row carries no
        # usable project authority; the on-ramp must still fail closed.
        item_id = _seed_item(conn)
        try:
            conn.execute(
                "INSERT INTO projects "
                "(id, slug, name, public_item_prefix, created_at) "
                "VALUES (0, 'none', 'No Project', 'YOK', "
                "'2026-05-01T00:00:00Z') "
                "ON CONFLICT (id) DO NOTHING"
            )
            conn.execute("UPDATE items SET project_id = 0 WHERE id = %s", (item_id,))
            conn.commit()
        except Exception:  # pragma: no cover - schema constraint absent
            pytest.skip("schema enforces project_id integrity")
        with pytest.raises(ItemHasNoProject):
            register_for_item(
                conn,
                item_id=item_id,
                integration_target="main",
                paths=["runtime/api/domain"],
                actor_id=local_human(conn),
            )
