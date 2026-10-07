"""The one item-identity resolver at the public identity boundary.

Item-ref resolution is control-plane authority behavior (it reads projects,
items and project identities), so it is proven against a disposable
real-Postgres database (``test_db``; conftest binds the local cluster) rather
than an in-memory SQLite double. The two projects share sequence 5 and their
internal ids differ from it, so a reading that confuses the counters fails.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import machine_config
from yoke_core.domain.item_ref_resolution import (
    ITEM_REF_INVALID,
    ITEM_REF_NEEDS_PROJECT,
    ITEM_REF_NOT_FOUND,
    ItemRefError,
    internal_ids_for_refs,
    internal_item_key,
    resolve_item_ref,
    resolve_item_ref_or_none,
)
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.yok_n_parser import parse_item_argument
from runtime.api.fixtures.backlog import insert_item

YOKE_ITEM_ID = 100
EXT_ITEM_ID = 200
SEQ = 5


@pytest.fixture()
def conn(test_db):
    c = test_db
    seed_project_identities(c)
    # Distinct public prefixes so PREFIX-N resolves unambiguously.
    c.execute(
        "UPDATE projects SET public_item_prefix = 'EXT' WHERE slug = 'externalwebapp'"
    )
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
    assert resolve_item_ref(conn, "YOK-5") == YOKE_ITEM_ID
    assert resolve_item_ref(conn, "ext-5") == EXT_ITEM_ID


def test_prefix_ref_ignores_project_context(conn):
    assert resolve_item_ref(conn, "EXT-5", project="yoke") == EXT_ITEM_ID


def test_bare_sequence_resolves_within_explicit_project(conn):
    assert resolve_item_ref(conn, "5", project="externalwebapp") == EXT_ITEM_ID
    assert resolve_item_ref(conn, "5", project=1) == YOKE_ITEM_ID


def test_bare_sequence_without_project_is_refused_with_the_fix(conn):
    with pytest.raises(ItemRefError) as exc:
        resolve_item_ref(conn, "5")
    assert exc.value.code == ITEM_REF_NEEDS_PROJECT
    assert "PREFIX-5" in str(exc.value)
    assert "--project" in str(exc.value)


def test_bare_number_is_never_an_internal_id(conn):
    # 100 is YOKE_ITEM_ID's internal id; it names no project sequence.
    with pytest.raises(ItemRefError):
        resolve_item_ref(conn, str(YOKE_ITEM_ID))
    with pytest.raises(ItemRefError) as exc:
        resolve_item_ref(conn, str(YOKE_ITEM_ID), project="yoke")
    assert exc.value.code == ITEM_REF_NOT_FOUND


@pytest.mark.parametrize("raw", ["yoke/YOK-5", "externalwebapp/5", "YOK5", "", 5, None])
def test_other_shapes_are_invalid(conn, raw):
    with pytest.raises(ItemRefError) as exc:
        resolve_item_ref(conn, raw)
    assert exc.value.code == ITEM_REF_INVALID


def test_unknown_ref_reports_not_found(conn):
    with pytest.raises(ItemRefError) as exc:
        resolve_item_ref(conn, "YOK-999")
    assert exc.value.code == ITEM_REF_NOT_FOUND
    assert resolve_item_ref_or_none(conn, "YOK-999") is None
    assert resolve_item_ref_or_none(conn, "5") is None


def test_bulk_refs_resolve_public_refs_only(conn):
    assert internal_ids_for_refs(conn, ["YOK-5", "EXT-5", "5", "YOK-999"]) == {
        "YOK-5": YOKE_ITEM_ID,
        "EXT-5": EXT_ITEM_ID,
    }


def test_scheduler_item_keys_are_engine_currency(conn):
    assert internal_item_key(conn, EXT_ITEM_ID) == EXT_ITEM_ID
    assert internal_item_key(conn, str(EXT_ITEM_ID)) == EXT_ITEM_ID
    assert internal_item_key(conn, "YOK-5") == YOKE_ITEM_ID
    assert internal_item_key(conn, None) is None


def test_argument_bare_sequence_refused_in_mapped_checkout(conn, monkeypatch):
    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: 2)
    with pytest.raises(ValueError, match="public_item_ref_required"):
        parse_item_argument("5", conn=conn)


def test_argument_without_mapped_context_fails_loudly(conn, monkeypatch):
    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: None)
    with pytest.raises(ValueError, match="public_item_ref_required"):
        parse_item_argument("5", conn=conn)


def test_argument_explicit_context_wins_over_mapped_checkout(conn, monkeypatch):
    monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: 1)
    assert (
        parse_item_argument("EXT-5", project="externalwebapp", conn=conn) == EXT_ITEM_ID
    )
