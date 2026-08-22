"""Shared CLI item-ref resolver at the public identity boundary.

Item-ref resolution is control-plane authority behavior (it reads projects,
items and project identities), so it is proven against a disposable
real-Postgres database (``test_db``; conftest binds the local cluster) rather
than an in-memory SQLite double.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import machine_config
from yoke_core.domain.project_identity_item_ref import resolve_cli_item_ref
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from runtime.api.fixtures.backlog import insert_item

YOKE_ITEM_ID = 100
EXT_ITEM_ID = 200
SEQ = 5


@pytest.fixture()
def conn(test_db):
    c = test_db
    seed_project_identities(c)
    # Distinct public prefixes so PREFIX-N resolves unambiguously.
    c.execute("UPDATE projects SET public_item_prefix = 'EXT' WHERE slug = 'externalwebapp'")
    c.execute("UPDATE projects SET public_item_prefix = 'YOK' WHERE slug = 'yoke'")
    for item_id, project_id in ((YOKE_ITEM_ID, 1), (EXT_ITEM_ID, 2)):
        insert_item(
            c,
            id=item_id,
            title="t",
            project_id=project_id,
            project_sequence=SEQ,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
    return c


def test_prefix_ref_resolves_by_prefix(conn):
    assert resolve_cli_item_ref(conn, "YOK-5") == YOKE_ITEM_ID
    assert resolve_cli_item_ref(conn, "EXT-5") == EXT_ITEM_ID


@pytest.mark.parametrize("raw", ["yoke/YOK-5", "externalwebapp/5"])
def test_retired_qualified_forms_are_refused(conn, raw):
    with pytest.raises(ValueError, match="project-qualified item refs are retired"):
        resolve_cli_item_ref(conn, raw)


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


def test_bare_sequence_without_mapped_context_fails_loudly(conn, monkeypatch):
    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: None)
    with pytest.raises(ValueError, match="bare numeric item refs are project-local"):
        resolve_cli_item_ref(conn, "5")


def test_explicit_context_wins_over_mapped_checkout(conn, monkeypatch):
    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: 1)
    assert (
        resolve_cli_item_ref(conn, "5", project_context="externalwebapp")
        == EXT_ITEM_ID
    )


def test_int_passthrough_is_internal_row_id(conn):
    # A real int is the internal id, returned as-is (when the row exists).
    assert resolve_cli_item_ref(conn, EXT_ITEM_ID) == EXT_ITEM_ID
