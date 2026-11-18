"""Migration 0113 records whose catalog each model catalog revision is."""

from pathlib import Path
import sqlite3

import pytest

from yoke_core.domain.migration_history import load_migration_module

_LEGACY = """
CREATE TABLE model_reference_revisions (
  revision_id TEXT PRIMARY KEY, effective_at TIMESTAMPTZ NOT NULL,
  published_at TIMESTAMPTZ NOT NULL, published_by_actor_id INTEGER,
  catalog_json TEXT NOT NULL, source_note TEXT NOT NULL, source_revision_id TEXT
)
"""


def _module():
    from yoke_core.domain import migrations

    path = Path(migrations.__file__).parent / "0113_model_reference_source.py"
    return load_migration_module(path, path.stem)


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_actor_published_revisions_become_operator_overrides(test_db, backend):
    if backend == "postgres":
        conn = test_db
        conn.execute("DELETE FROM model_reference_revisions")
        conn.execute("ALTER TABLE model_reference_revisions DROP COLUMN source")
    else:
        conn = sqlite3.connect(":memory:")
        conn.execute(_LEGACY)
    for revision_id, actor in (("seed", None), ("published", 2)):
        conn.execute(
            "INSERT INTO model_reference_revisions VALUES "
            f"('{revision_id}', '2026-09-23T00:00:00Z', '2026-09-23T00:00:00Z', "
            f"{'NULL' if actor is None else actor}, '[]', 'note', NULL)"
        )
    migration = _module()
    migration.apply(conn)
    migration.apply(conn)
    migration.invariants(conn)
    rows = dict(
        conn.execute(
            "SELECT revision_id, source FROM model_reference_revisions"
        ).fetchall()
    )
    assert rows == {"seed": "shipped", "published": "operator"}
