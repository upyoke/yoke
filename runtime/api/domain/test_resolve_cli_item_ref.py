"""Shared CLI item-ref resolver + bare-number ladder, on real Postgres.

Item-ref resolution is control-plane authority behavior (it reads projects,
items, and the actor's org/project grants), so it is proven against a disposable
real-Postgres database (``test_db``; conftest binds the local cluster) rather
than an in-memory SQLite double.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import machine_config
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_identity_item_ref import (
    AmbiguousItemProjectContext,
    resolve_cli_item_ref,
)
from yoke_core.domain.project_seed_test_helpers import seed_project_identities

YOKE_ITEM_ID = 100
EXT_ITEM_ID = 200
SEQ = 5


@pytest.fixture()
def conn(test_db):
    c = test_db
    seed_project_identities(c)
    seed_roles_and_permissions(c)
    seed_default_org(c)
    # Distinct public prefixes so PREFIX-N resolves unambiguously.
    c.execute("UPDATE projects SET public_item_prefix = 'EXT' WHERE slug = 'externalwebapp'")
    c.execute("UPDATE projects SET public_item_prefix = 'YOK' WHERE slug = 'yoke'")
    for item_id, project_id in ((YOKE_ITEM_ID, 1), (EXT_ITEM_ID, 2)):
        c.execute(
            "INSERT INTO items (id, title, created_at, updated_at, project_id, "
            "project_sequence) VALUES (%s, 't', '2026-01-01T00:00:00Z', "
            "'2026-01-01T00:00:00Z', %s, %s)",
            (item_id, project_id, SEQ),
        )
    c.commit()
    return c


def test_prefix_ref_resolves_by_prefix(conn):
    assert resolve_cli_item_ref(conn, "YOK-5") == YOKE_ITEM_ID
    assert resolve_cli_item_ref(conn, "EXT-5") == EXT_ITEM_ID


def test_qualified_slug_prefix_ref(conn):
    assert resolve_cli_item_ref(conn, "yoke/YOK-5") == YOKE_ITEM_ID
    assert resolve_cli_item_ref(conn, "externalwebapp/EXT-5") == EXT_ITEM_ID


def test_qualified_slug_bare_sequence(conn):
    assert resolve_cli_item_ref(conn, "externalwebapp/5") == EXT_ITEM_ID


def test_bare_sequence_with_explicit_context(conn):
    assert (
        resolve_cli_item_ref(conn, "5", project_context="externalwebapp") == EXT_ITEM_ID
    )
    assert (
        resolve_cli_item_ref(conn, "5", project_context="yoke") == YOKE_ITEM_ID
    )


def test_bare_sequence_via_cwd_checkout(conn, monkeypatch):
    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: 2)
    assert resolve_cli_item_ref(conn, "5") == EXT_ITEM_ID


def test_bare_sequence_ambiguous_fails_loudly(conn, monkeypatch):
    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: None)
    monkeypatch.setattr(machine_config, "installed_project_ids", lambda *_a, **_k: {1, 2})
    with pytest.raises(AmbiguousItemProjectContext):
        resolve_cli_item_ref(conn, "5")


def test_actor_access_narrows_ambiguity(conn, monkeypatch):
    actor_id = seed_human_actor(conn)
    grant_actor_project_role(
        conn, actor_id=actor_id, project_id=1, role_name=ROLE_OWNER
    )
    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: None)
    monkeypatch.setattr(machine_config, "installed_project_ids", lambda *_a, **_k: {1, 2})
    # Two installed, but actor can only reach yoke -> unambiguous.
    assert resolve_cli_item_ref(conn, "5", actor_id=actor_id) == YOKE_ITEM_ID


def test_int_passthrough_is_internal_row_id(conn):
    # A real int is the internal id, returned as-is (when the row exists).
    assert resolve_cli_item_ref(conn, EXT_ITEM_ID) == EXT_ITEM_ID
