"""Shared seeds + file editing helpers for the strategy-doc test modules.

Consumed by ``test_strategy_docs*.py`` (domain reads/writes, render,
ingest plan/execute) so each test module stays under the authored-file
line cap without duplicating fixture plumbing. Two projects (the schema
seed's ids 1 and 2) exercise per-project isolation.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import strategy_docs as sd
from yoke_core.domain.strategy_docs_paths import strategy_view_path
from runtime.api.fixtures.file_test_db import connect_test_db

SEED_UPDATED_AT = "2026-06-10T00:00:00Z"

# Fixture corpus deliberately larger than the default starter canon so
# ordering (defaults first, extras alphabetical after) is observable.
SEED_SLUGS = ("MISSION", "VISION", "MASTER-PLAN", "LANDSCAPE", "PAD", "WISPS")

SEED_CONTENT = {
    slug: f"# {slug}\n\nseeded body for {slug}.\nLine two.\n"
    for slug in SEED_SLUGS
}

PROJECT_A = 1
PROJECT_B = 2


def insert_doc(
    conn, project_id: int, slug: str, content: str,
    updated_at: str = SEED_UPDATED_AT,
) -> None:
    conn.execute(
        f"INSERT INTO {sd.STRATEGY_DOCS_TABLE} "
        "(project_id, slug, content, updated_at) VALUES (%s, %s, %s, %s)",
        (project_id, slug, content, updated_at),
    )


def seed_docs(conn, project_id: int = PROJECT_A, *, skip: tuple = ()) -> None:
    for slug in SEED_SLUGS:
        if slug in skip:
            continue
        insert_doc(conn, project_id, slug, SEED_CONTENT[slug])
    conn.commit()


def edit_body(root: Path, slug: str, new_body: str) -> None:
    """Replace a rendered file's body while keeping its header line."""
    path = strategy_view_path(root, slug)
    first_line, _, _ = path.read_text(encoding="utf-8").partition("\n")
    path.write_text(first_line + "\n" + new_body, encoding="utf-8")


def bump_db_row(tmp_db: str, slug: str, project_id: int = PROJECT_A) -> None:
    """Simulate another writer moving the row after the render."""
    conn = connect_test_db(tmp_db)
    try:
        conn.execute(
            f"UPDATE {sd.STRATEGY_DOCS_TABLE} "
            "SET content = %s, updated_at = %s "
            "WHERE project_id = %s AND slug = %s",
            (SEED_CONTENT[slug] + "\nDB moved on.\n", "2026-06-11T11:11:11Z",
             project_id, slug),
        )
        conn.commit()
    finally:
        conn.close()


def fetch_row(conn, project_id: int, slug: str):
    return conn.execute(
        f"SELECT content, updated_at, updated_by_actor_id "
        f"FROM {sd.STRATEGY_DOCS_TABLE} "
        "WHERE project_id = %s AND slug = %s",
        (project_id, slug),
    ).fetchone()


__all__ = [
    "PROJECT_A",
    "PROJECT_B",
    "SEED_CONTENT",
    "SEED_SLUGS",
    "SEED_UPDATED_AT",
    "bump_db_row",
    "edit_body",
    "fetch_row",
    "insert_doc",
    "seed_docs",
]
