"""Batch refresh preserves relationship values without rewriting current rows."""

from __future__ import annotations

import json
from time import perf_counter

import pytest

from runtime.api.path_context_test_helpers import init_minimal_schema
from yoke_core.domain import agents_render_path_context as subject


@pytest.fixture
def conn(tmp_path):
    connection = init_minimal_schema(str(tmp_path / "relationships.db"))
    try:
        yield connection
    finally:
        connection.close()


def seed_paths(conn, paths):
    conn.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, created_at) "
        "SELECT 1, 'file', p, 1, now() FROM unnest(%s::text[]) AS p",
        (sorted(paths),),
    )


def stored_rows(conn):
    return [tuple(row) for row in conn.execute(
        "SELECT id, target_id, context_family, entry_key, value, "
        "recorded_event_id, recorded_at FROM path_context_values ORDER BY id"
    ).fetchall()]


def values(conn):
    return {
        (row[1], row[2], row[3]): json.loads(row[4]) for row in stored_rows(conn)
    }


def test_batch_matches_single_relationship_writer(conn, monkeypatch):
    relationships = {
        "output-a": ["seed-b", "seed-a", "seed-a", "missing-seed", ""],
        "output-b": ["seed-b"],
        "missing-output": ["seed-a"],
    }
    seed_paths(conn, ["output-a", "output-b", "seed-a", "seed-b"])
    monkeypatch.setattr(subject, "render_relationship_map", lambda _: relationships)
    for target, sources in relationships.items():
        subject.set_render_relationship(
            conn, project_id=1, target_path=target,
            source_paths=sources, recorded_event_id="single-operation",
        )
    expected = values(conn)
    conn.execute("DELETE FROM path_context_values")
    assert subject.record_render_relationships(conn, project_id=1) == 2
    assert values(conn) == expected
    original = stored_rows(conn)
    assert subject.record_render_relationships(conn, project_id=1) == 2
    assert stored_rows(conn) == original


def test_batch_updates_only_changed_values_and_preserves_other_rows(conn, monkeypatch):
    relationships = {"output-a": ["seed-a"], "output-b": ["seed-b"]}
    seed_paths(conn, ["output-a", "output-b", "seed-a", "seed-b"])
    monkeypatch.setattr(subject, "render_relationship_map", lambda _: relationships)
    subject.record_render_relationships(conn, project_id=1)
    # Formatting alone is not a change; unrelated families are not render truth.
    conn.execute(
        "UPDATE path_context_values SET value = %s "
        "WHERE context_family = 'render_target' AND value::jsonb = %s::jsonb",
        ('{ "sources" : [ "seed-a" ] }', '{"sources":["seed-a"]}'),
    )
    conn.execute(
        "INSERT INTO path_context_values "
        "(target_id, context_family, entry_key, value, recorded_event_id, recorded_at) "
        "SELECT min(id), 'posture', 'generated', '{}', 'original', now() "
        "FROM path_targets"
    )
    before = {row[0]: row for row in stored_rows(conn)}
    changed_id = conn.execute(
        "UPDATE path_context_values SET value = '{}' "
        "WHERE context_family='render_source' AND entry_key='output-b' RETURNING id"
    ).fetchone()[0]
    assert subject.record_render_relationships(conn, project_id=1) == 2
    after = {row[0]: row for row in stored_rows(conn)}
    assert set(after) == set(before)
    assert after[changed_id][4] == before[changed_id][4]
    assert after[changed_id][5] != before[changed_id][5]
    assert {key: row for key, row in after.items() if key != changed_id} == {
        key: row for key, row in before.items() if key != changed_id
    }


def test_large_no_change_render_uses_one_context_read_and_no_writes(conn, monkeypatch):
    sources = [f"seed-{index}" for index in range(75)]
    relationships = {f"output-{index}": sources for index in range(200)}
    seed_paths(conn, [*relationships, *sources])
    monkeypatch.setattr(subject, "render_relationship_map", lambda _: relationships)
    original_execute = conn.execute
    queries = []

    def counting(sql, params=()):
        queries.append(str(sql))
        return original_execute(sql, params)

    conn.execute = counting
    assert subject.record_render_relationships(conn, project_id=1) == 200
    assert sum("INSERT INTO path_context_values" in sql for sql in queries) == 1
    assert conn.execute("SELECT count(*) FROM path_context_values").fetchone()[0] == 15200
    original = stored_rows(conn)
    queries.clear()
    started = perf_counter()
    assert subject.record_render_relationships(conn, project_id=1) == 200
    duration = perf_counter() - started
    assert sum("FROM path_context_values" in sql for sql in queries) == 1
    assert not any("INSERT INTO path_context_values" in sql for sql in queries)
    assert not any("UPDATE path_context_values" in sql for sql in queries)
    assert not any("SELECT 1 FROM path_targets" in sql for sql in queries)
    assert stored_rows(conn) == original
    print(f"no_change_render: rows=15200 duration_ms={duration * 1000:.3f}")
