"""Architecture-health board section rendering.

The section lists coverage for every scoped project that declares an
architecture map, using the same inherited-context semantics as the
health computer, and collapses entirely when no scoped map exists.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from yoke_core.board.db import BoardDB
from yoke_contracts.board.sections_architecture import (
    render_architecture_section,
)
from runtime.api.fixtures.file_test_db import (
    apply_inline_ddl,
    init_test_db,
)


_SCHEMA = """
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY,
        slug TEXT UNIQUE,
        name TEXT DEFAULT '',
        public_item_prefix TEXT DEFAULT 'YOK'
    );
    CREATE TABLE project_structure (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL,
        family TEXT NOT NULL,
        payload TEXT
    );
    CREATE TABLE path_targets (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL,
        kind TEXT NOT NULL DEFAULT 'file',
        path_string TEXT NOT NULL,
        parent_target_id INTEGER
    );
    CREATE TABLE path_snapshots (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL,
        commit_sha TEXT NOT NULL,
        built_at TEXT NOT NULL
    );
    CREATE TABLE path_snapshot_entries (
        id INTEGER PRIMARY KEY,
        snapshot_id INTEGER NOT NULL,
        target_id INTEGER NOT NULL,
        language TEXT,
        dependency_edges TEXT
    );
    CREATE TABLE path_context_values (
        id INTEGER PRIMARY KEY,
        target_id INTEGER NOT NULL,
        context_family TEXT NOT NULL,
        entry_key TEXT NOT NULL DEFAULT '',
        value TEXT NOT NULL
    );
"""


@contextlib.contextmanager
def _board_db(tmp_path: Path, seed_sql: str):
    with init_test_db(
        tmp_path,
        apply_schema=lambda: apply_inline_ddl(_SCHEMA + seed_sql),
    ) as db_path:
        db = BoardDB(db_path)
        try:
            yield db
        finally:
            db.close()


def test_collapses_when_no_scoped_map_exists(tmp_path: Path) -> None:
    seed = "INSERT INTO projects (id, slug) VALUES (1, 'plain');"
    with _board_db(tmp_path, seed) as db:
        assert render_architecture_section(db, "all") == ""


def test_reports_coverage_with_inherited_context(tmp_path: Path) -> None:
    seed = """
    INSERT INTO projects (id, slug) VALUES (1, 'mapped');
    INSERT INTO project_structure (id, project_id, family, payload)
        VALUES (1, 1, 'architecture_model', '{}');
    INSERT INTO path_targets (id, project_id, kind, path_string,
                              parent_target_id)
        VALUES (10, 1, 'dir', 'tests', NULL),
               (11, 1, 'file', 'src/direct.py', NULL),
               (12, 1, 'file', 'tests/inherited.py', 10),
               (13, 1, 'file', 'scripts/uncovered.py', NULL);
    INSERT INTO path_snapshots (id, project_id, commit_sha, built_at)
        VALUES (500, 1, 'aaa', '2026-01-01T00:00:00Z');
    INSERT INTO path_snapshot_entries
        (id, snapshot_id, target_id, language, dependency_edges)
        VALUES (1, 500, 11, 'python', '[]'),
               (2, 500, 12, 'python', '[]'),
               (3, 500, 13, 'python', '[]');
    INSERT INTO path_context_values
        (id, target_id, context_family, entry_key, value)
        VALUES (1, 11, 'architecture_layer', '', '{"layer": "domain"}'),
               (2, 10, 'architecture_test_surface', '', '{"glob": "tests/**"}');
    """
    with _board_db(tmp_path, seed) as db:
        text = render_architecture_section(db, "all")
    assert "Architecture" in text
    assert "mapped: 66.7% classified" in text
    assert "1 unclassified of 3 python files" in text
    assert "architecture-health get" in text


def test_declared_map_without_snapshot_reads_calmly(tmp_path: Path) -> None:
    seed = """
    INSERT INTO projects (id, slug) VALUES (1, 'young');
    INSERT INTO project_structure (id, project_id, family, payload)
        VALUES (1, 1, 'architecture_model', '{}');
    """
    with _board_db(tmp_path, seed) as db:
        text = render_architecture_section(db, "all")
    assert "young: map declared · no snapshot yet" in text
