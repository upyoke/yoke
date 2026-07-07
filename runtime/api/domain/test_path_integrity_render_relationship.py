"""Tests for the render-relationship path-integrity invariant.

Lives in its own file because `test_path_integrity.py` is already over
the 300-line design target. The invariant under test is wired into
`HC-path-integrity` via the existing invariant registry, so
operator-visible drift surfaces through the existing doctor check.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain._path_integrity_test_helpers import path_integrity_db
from yoke_core.domain.path_integrity_invariants_render_relationship import (
    check_render_relationship,
)

_CORE_DOMAIN_SOURCE_ROOT = "packages/yoke-core/src/yoke_core/domain"


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_project(conn: Any) -> None:
    conn.execute(
        "INSERT INTO projects (id, slug, name, created_at) "
        "VALUES (1, 'yoke', 'yoke', '2026-05-01T00:00:00Z') "
        "ON CONFLICT DO NOTHING"
    )
    conn.commit()


def _seed_target(conn: Any, *, path_string: str) -> int:
    p = _p(conn)
    cur = conn.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, created_at) "
        f"VALUES (1, 'file', {p}, 1, '2026-05-01T00:00:00Z') "
        "RETURNING id",
        (path_string,),
    )
    return int(cur.fetchone()[0])


def _seed_event(conn: Any) -> str:
    event_id = "test-event-render-rel-1"
    p = _p(conn)
    conn.execute(
        "INSERT INTO events (event_id, event_name, event_kind, event_type, "
        "source_type, session_id, severity, event_outcome, created_at) "
        f"VALUES ({p}, 'RenderRelationshipRecorded', 'lifecycle', "
        "'path_context', 'backend', '', 'INFO', 'completed', "
        "'2026-05-01T00:00:00Z')",
        (event_id,),
    )
    return event_id


def _seed_render_target_row(
    conn: Any,
    *,
    target_id: int,
    sources: list[str],
    event_id: str,
) -> None:
    p = _p(conn)
    conn.execute(
        "INSERT INTO path_context_values "
        "(target_id, context_family, entry_key, value, "
        " recorded_event_id, recorded_at) "
        f"VALUES ({p}, 'render_target', '', {p}, {p}, '2026-05-01T00:00:00Z')",
        (target_id, json.dumps({"sources": sources}), event_id),
    )


@pytest.fixture
def fresh_db(tmp_path):
    with path_integrity_db(tmp_path) as conn:
        _seed_project(conn)
        yield conn


def test_no_render_target_rows_returns_empty(fresh_db):
    assert check_render_relationship(fresh_db, 1) == []


def test_honest_target_with_registered_sources_returns_empty(fresh_db):
    event_id = _seed_event(fresh_db)
    target_id = _seed_target(
        fresh_db, path_string="runtime/harness/claude/agents/yoke-x.md",
    )
    _seed_target(fresh_db, path_string="runtime/agents/x.md")
    _seed_target(fresh_db, path_string=f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render.py")
    _seed_render_target_row(
        fresh_db,
        target_id=target_id,
        sources=[
            "runtime/agents/x.md",
            f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render.py",
        ],
        event_id=event_id,
    )
    assert check_render_relationship(fresh_db, 1) == []


def test_stale_target_surfaces_failure(fresh_db):
    event_id = _seed_event(fresh_db)
    target_id = _seed_target(
        fresh_db, path_string="runtime/harness/claude/agents/yoke-y.md",
    )
    _seed_render_target_row(
        fresh_db,
        target_id=target_id,
        sources=["runtime/agents/y.md"],
        event_id=event_id,
    )
    # Simulate the "row points at a deleted target" drift this invariant
    # is the defense-in-depth backstop for.
    if db_backend.connection_is_postgres(fresh_db):
        fresh_db.execute(
            "ALTER TABLE path_context_values DROP CONSTRAINT IF EXISTS "
            "path_context_values_target_id_fkey"
        )
    p = _p(fresh_db)
    fresh_db.execute(
        f"DELETE FROM path_targets WHERE id={p}", (target_id,),
    )
    fresh_db.commit()
    failures = check_render_relationship(fresh_db, 1)
    assert len(failures) == 1
    _, detail = failures[0]
    assert detail["kind"] == "stale_target"


def test_unregistered_seed_source_surfaces_failure(fresh_db):
    event_id = _seed_event(fresh_db)
    target_id = _seed_target(
        fresh_db, path_string="runtime/harness/claude/agents/yoke-z.md",
    )
    _seed_target(fresh_db, path_string="runtime/agents/z.md")
    _seed_render_target_row(
        fresh_db,
        target_id=target_id,
        sources=[
            "runtime/agents/z.md",
            "runtime/api/domain/never_seeded.py",
        ],
        event_id=event_id,
    )
    failures = check_render_relationship(fresh_db, 1)
    assert len(failures) == 1
    _, detail = failures[0]
    assert detail["kind"] == "unregistered_source"
    assert detail["missing_source"] == "runtime/api/domain/never_seeded.py"


def test_invariant_registered_in_funcs(fresh_db):
    from yoke_core.domain.path_integrity_invariants import (
        ALL_INVARIANTS,
        INVARIANT_FUNCS,
        INVARIANT_RENDER_RELATIONSHIP,
    )
    assert INVARIANT_RENDER_RELATIONSHIP in ALL_INVARIANTS
    names = {name for name, _fn in INVARIANT_FUNCS}
    assert INVARIANT_RENDER_RELATIONSHIP in names
