"""Tests for the render-relationship path-context families.

Cover the constants exported by `path_context.py`, the helpers
in `agents_render_path_context.py`, and the renderer-self-registration
shape of `render_relationship_map`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import db_backend, path_context
from yoke_core.domain.agents_render import AGENTS
from yoke_core.domain.agents_render_conditional import (
    HARNESS_IDS,
    rendered_agent_path,
)
from yoke_core.domain.agents_render_path_context import (
    read_render_source_for,
    record_render_relationships,
    render_relationship_map,
    set_render_relationship,
)
from yoke_core.domain.populate_registry_render import EVENT_CATALOG_RELPATH
from yoke_core.domain.events_schema import ensure_event_schema
from yoke_core.domain.schema_init_tables import (
    create_core_tables,
    create_governed_tables,
    create_path_integrity_tables,
    create_path_registry_tables,
)
from yoke_contracts.project_contract.install_manifest import (
    PACKAGED_INSTALL_BUNDLE_TREE_REL,
)
from yoke_core.tools.atlas_render_docs import ATLAS_RELPATH
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

_CORE_DOMAIN_SOURCE_ROOT = "packages/yoke-core/src/yoke_core/domain"


def _apply_path_context_schema() -> None:
    """Build the render-relationship schema on the active test backend."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS projects ("
            "id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, "
            "name TEXT NOT NULL, "
            "default_branch TEXT NOT NULL DEFAULT 'main', "
            "github_repo TEXT, public_item_prefix TEXT NOT NULL DEFAULT 'YOK', "
            "created_at TEXT NOT NULL)"
        )
        create_core_tables(conn)
        create_governed_tables(conn)
        ensure_event_schema(conn)
        create_path_registry_tables(conn)
        create_path_integrity_tables(conn)
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, created_at) "
            "VALUES (1, 'yoke', 'yoke', '2026-05-01T00:00:00Z') "
            "ON CONFLICT DO NOTHING"
        )
        conn.commit()
    finally:
        conn.close()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_target(conn, *, path_string: str) -> int:
    p = _p(conn)
    cur = conn.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, created_at) "
        f"VALUES (1, 'file', {p}, 1, '2026-05-01T00:00:00Z') "
        "RETURNING id",
        (path_string,),
    )
    return int(cur.fetchone()[0])


def _seed_event(conn, *, event_id: str) -> str:
    p = _p(conn)
    conn.execute(
        "INSERT INTO events (event_id, event_name, event_kind, "
        "event_type, source_type, session_id, severity, event_outcome, "
        f"created_at) VALUES ({p}, 'RenderRelationshipRecorded', 'lifecycle', "
        "'path_context', 'backend', '', 'INFO', 'completed', "
        "'2026-05-01T00:00:00Z') ON CONFLICT DO NOTHING",
        (event_id,),
    )
    return event_id


@pytest.fixture
def fresh_db(tmp_path):
    with init_test_db(tmp_path, apply_schema=_apply_path_context_schema) as path:
        conn = connect_test_db(path)
        try:
            yield conn
        finally:
            conn.close()


def test_family_constants_exported():
    assert path_context.FAMILY_RENDER_TARGET == "render_target"
    assert path_context.FAMILY_RENDER_SOURCE == "render_source"
    assert path_context.FAMILY_RENDER_TARGET in path_context.KNOWN_FAMILIES
    assert path_context.FAMILY_RENDER_SOURCE in path_context.KNOWN_FAMILIES
    assert (
        path_context.FAMILY_RENDER_TARGET
        in path_context.RENDER_RELATIONSHIP_FAMILIES
    )


def test_render_relationship_map_covers_every_agent_packet():
    relationships = render_relationship_map()
    expected = {
        rendered_agent_path(harness_id, agent).as_posix()
        for harness_id in HARNESS_IDS
        for agent in AGENTS
    }
    assert expected <= relationships.keys()
    assert len(expected) == len(HARNESS_IDS) * len(AGENTS)
    for target_path in expected:
        assert relationships[target_path]
        assert relationships[target_path] == sorted(relationships[target_path])


def test_render_relationship_map_includes_canonical_body():
    relationships = render_relationship_map()
    target = "runtime/harness/claude/agents/yoke-engineer.md"
    sources = relationships[target]
    assert "runtime/agents/engineer.md" in sources


def test_render_relationship_paths_exist_on_live_tree():
    repo_root = Path(__file__).resolve().parents[3]
    relationships = render_relationship_map()
    on_demand_targets = {ATLAS_RELPATH}
    missing = [
        path
        for path in sorted(
            set(relationships).union(*(set(sources) for sources in relationships.values()))
        )
        if path not in on_demand_targets and not (repo_root / path).exists()
    ]
    assert missing == []


def test_render_relationship_map_derives_every_tracked_bundle_mirror():
    repo_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = set(result.stdout.splitlines())
    relationships = render_relationship_map(tracked)
    prefix = f"{PACKAGED_INSTALL_BUNDLE_TREE_REL}/"
    mirrors = {path for path in tracked if path.startswith(prefix)}
    assert mirrors <= relationships.keys()
    for target_path in mirrors:
        source_path = target_path[len(prefix) :]
        expected_source = source_path if source_path in tracked else target_path
        assert relationships[target_path] == [expected_source]


def test_partially_generated_authored_surfaces_are_conservative():
    partial = {
        "AGENTS.md",
        "packages/yoke-core/src/yoke_core/ui/static/app.css",
    }
    relationships = render_relationship_map(partial)
    assert partial.isdisjoint(relationships)
    assert EVENT_CATALOG_RELPATH in relationships[EVENT_CATALOG_RELPATH]


def test_render_relationship_map_bash_capable_inherits_schema_api_context():
    relationships = render_relationship_map()
    sources = relationships["runtime/harness/claude/agents/yoke-architect.md"]
    assert any(s.startswith(f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context") for s in sources)


def test_render_relationship_map_non_bash_no_schema_api_context():
    relationships = render_relationship_map()
    sources = relationships[
        "runtime/harness/claude/agents/yoke-product-manager.md"
    ]
    assert not any(
        s.startswith(f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context") for s in sources
    )


def test_set_and_read_render_relationship_roundtrip(fresh_db):
    event_id = _seed_event(fresh_db, event_id="ev-rel-1")
    target_id = _seed_target(
        fresh_db, path_string="runtime/harness/claude/agents/yoke-arch.md",
    )
    _seed_target(fresh_db, path_string="runtime/agents/arch.md")
    _seed_target(fresh_db, path_string=f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render.py")
    set_render_relationship(
        fresh_db,
        target_path="runtime/harness/claude/agents/yoke-arch.md",
        source_paths=[
            "runtime/agents/arch.md",
            f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render.py",
        ],
        recorded_event_id=event_id,
    )
    sources = read_render_source_for(fresh_db, target_id=target_id)
    assert sources == sorted([
        "runtime/agents/arch.md",
        f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render.py",
    ])


def test_set_render_relationship_skips_when_target_unknown(fresh_db):
    event_id = _seed_event(fresh_db, event_id="ev-rel-skip")
    # No path_targets row for this path_string — helper returns None.
    result = set_render_relationship(
        fresh_db,
        target_path="runtime/harness/claude/agents/yoke-never-seeded.md",
        source_paths=["runtime/agents/x.md"],
        recorded_event_id=event_id,
    )
    assert result is None


def test_set_render_relationship_is_idempotent(fresh_db):
    event_id_1 = _seed_event(fresh_db, event_id="ev-rel-idem-1")
    event_id_2 = _seed_event(fresh_db, event_id="ev-rel-idem-2")
    target_id = _seed_target(
        fresh_db, path_string="runtime/harness/codex/agents/yoke-boss.toml",
    )
    _seed_target(fresh_db, path_string="runtime/agents/boss.md")
    set_render_relationship(
        fresh_db,
        target_path="runtime/harness/codex/agents/yoke-boss.toml",
        source_paths=["runtime/agents/boss.md"],
        recorded_event_id=event_id_1,
    )
    set_render_relationship(
        fresh_db,
        target_path="runtime/harness/codex/agents/yoke-boss.toml",
        source_paths=["runtime/agents/boss.md"],
        recorded_event_id=event_id_2,
    )
    count = fresh_db.execute(
        "SELECT COUNT(*) FROM path_context_values "
        f"WHERE target_id={_p(fresh_db)} AND context_family='render_target'",
        (target_id,),
    ).fetchone()[0]
    assert count == 1


def test_record_render_relationships_writes_zero_when_no_targets(fresh_db):
    written = record_render_relationships(fresh_db)
    assert written == 0


def test_record_render_relationships_writes_known_targets(fresh_db):
    relationships = render_relationship_map()
    for target_path in relationships:
        _seed_target(fresh_db, path_string=target_path)
    fresh_db.commit()
    written = record_render_relationships(fresh_db)
    assert written == len(relationships)
    rows = fresh_db.execute(
        "SELECT COUNT(*) FROM path_context_values "
        "WHERE context_family='render_target'"
    ).fetchone()[0]
    assert rows == len(relationships)


def test_generated_docs_and_bundle_mirror_resolve_seed_sources(fresh_db):
    prefix = f"{PACKAGED_INSTALL_BUNDLE_TREE_REL}/"
    source_path = ".agents/skills/yoke/SKILL.md"
    bundle_target = f"{prefix}{source_path}"
    targets = [ATLAS_RELPATH, EVENT_CATALOG_RELPATH, bundle_target]
    target_ids = {path: _seed_target(fresh_db, path_string=path) for path in targets}
    _seed_target(fresh_db, path_string=source_path)
    fresh_db.commit()

    assert record_render_relationships(fresh_db) == len(targets)
    for target_path in targets:
        sources = read_render_source_for(
            fresh_db,
            target_id=target_ids[target_path],
        )
        assert sources, target_path
    assert read_render_source_for(
        fresh_db,
        target_id=target_ids[bundle_target],
    ) == [source_path]
