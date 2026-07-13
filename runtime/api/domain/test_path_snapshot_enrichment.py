"""Tests for ``path_snapshot_enrichment``: per-entry enrichment column
computation (AC-4 population).

The pure functions (line_count / language / module_name / dependency
edges) test directly; ``enrich_entry`` and the inherited-context
readers exercise the full DB-aware path via the path_context test
helpers fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import path_snapshot_enrichment as enrich
from yoke_core.domain import path_context
from yoke_core.domain._path_snapshots_test_helpers import path_snapshot_db
from runtime.api.path_context_test_helpers import (
    emit_event,
    init_minimal_schema,
    mint_target,
)


@pytest.fixture
def conn(tmp_path: Path):
    db_path = str(tmp_path / "test.db")
    c = init_minimal_schema(db_path)
    yield c
    c.close()


class TestPureColumnHelpers:
    @pytest.mark.parametrize("source,expected", [
        ("", 0),
        ("one\n", 1),
        ("one\ntwo\n", 2),
        ("one\ntwo", 2),  # no trailing newline still counts both lines
        ("\n\n", 2),
    ])
    def test_line_count(self, source, expected):
        assert enrich.compute_line_count(source) == expected

    @pytest.mark.parametrize("path,language", [
        ("a.py", "python"),
        ("docs/OVERVIEW.md", "markdown"),
        ("fixtures/config.json", "json"),
        ("ci.yaml", "yaml"),
        ("ci.yml", "yaml"),
        ("run.sh", "shell"),
        ("ui.tsx", "typescript"),
        ("ui.ts", "typescript"),
        ("ui.jsx", "javascript"),
        ("ui.js", "javascript"),
        ("page.html", "html"),
        ("theme.css", "css"),
        ("schema.sql", "sql"),
        ("unknown.xyz", None),
        ("no_ext", None),
    ])
    def test_infer_language(self, path, language):
        assert enrich.infer_language(path) == language

    @pytest.mark.parametrize("path,module", [
        ("runtime/api/domain/foo.py", "yoke_core.domain.foo"),
        ("runtime/api/__init__.py", "yoke_core"),
        ("docs/OVERVIEW.md", None),
        ("foo.sh", None),
    ])
    def test_compute_module_name(self, path, module):
        assert enrich.compute_module_name(path) == module


class TestDependencyEdgeComputation:
    def test_python_file_emits_edges(self):
        result = enrich.compute_dependency_edges(
            "import json\nfrom os import path\n",
            "runtime/api/domain/foo.py",
        )
        assert result["scan_error"] is None
        assert {"source_module": "yoke_core.domain.foo",
                "imported_module": "json",
                "imported_name": "json"} in result["edges"]
        assert {"source_module": "yoke_core.domain.foo",
                "imported_module": "os",
                "imported_name": "path"} in result["edges"]

    def test_non_python_file_has_empty_edges_no_error(self):
        result = enrich.compute_dependency_edges(
            "# title\nbody\n", "docs/OVERVIEW.md",
        )
        assert result == {"edges": [], "scan_error": None}

    def test_syntax_error_surfaces_as_scan_error(self):
        result = enrich.compute_dependency_edges(
            "def broken(\n", "p.py",
        )
        assert result["edges"] == []
        assert result["scan_error"] is not None
        assert "SyntaxError" in result["scan_error"]


class TestEnrichEntry:
    def test_defaults_for_uncontextualized_python_module(
        self, conn
    ):
        target_id = mint_target(conn, "yoke", "runtime/api/domain/foo.py")
        cols = enrich.enrich_entry(
            conn,
            target_id=target_id,
            source="import json\n",
            path_string="runtime/api/domain/foo.py",
        )
        assert cols.line_count == 1
        assert cols.language == "python"
        assert cols.module_name == "yoke_core.domain.foo"
        assert cols.area is None
        assert cols.is_generated == 0
        edges = json.loads(cols.dependency_edges)
        assert edges == [{
            "imported_module": "json",
            "imported_name": "json",
            "source_module": "yoke_core.domain.foo",
        }]
        assert cols.scan_error is None

    def test_area_inherits_from_parent(self, conn):
        parent = mint_target(
            conn, "yoke", "runtime/api/domain", kind="directory",
        )
        child = mint_target(
            conn, "yoke", "runtime/api/domain/foo.py",
            parent_target_id=parent,
        )
        event_id = emit_event(conn, name="AreaAssigned")
        path_context.put_context_value(
            conn,
            target_id=parent,
            context_family=path_context.FAMILY_POSTURE,
            entry_key="area",
            value={"area": "backend"},
            recorded_event_id=event_id,
        )
        conn.commit()
        cols = enrich.enrich_entry(
            conn,
            target_id=child,
            source="",
            path_string="runtime/api/domain/foo.py",
        )
        assert cols.area == "backend"

    def test_is_generated_inherits_from_exemption_family(
        self, conn
    ):
        parent = mint_target(
            conn, "yoke", "ux-specs", kind="directory",
        )
        child = mint_target(
            conn, "yoke", "ux-specs/build/page.html",
            parent_target_id=parent,
        )
        event_id = emit_event(conn, name="GeneratedAssigned")
        path_context.put_context_value(
            conn,
            target_id=parent,
            context_family=path_context.FAMILY_GENERATED,
            entry_key="",
            value={"reason": "build_output"},
            recorded_event_id=event_id,
        )
        conn.commit()
        cols = enrich.enrich_entry(
            conn,
            target_id=child,
            source="<html></html>\n",
            path_string="ux-specs/build/page.html",
        )
        assert cols.is_generated == 1
        assert cols.language == "html"
        assert cols.module_name is None
        assert cols.dependency_edges == "[]"

    def test_scan_error_surfaces_without_raising(
        self, conn
    ):
        target_id = mint_target(
            conn, "yoke", "runtime/api/domain/broken.py",
        )
        cols = enrich.enrich_entry(
            conn,
            target_id=target_id,
            source="def broken(\n",
            path_string="runtime/api/domain/broken.py",
        )
        assert cols.scan_error is not None
        edges = json.loads(cols.dependency_edges)
        assert edges == [{
            "imported_module": "",
            "imported_name": "",
            "scan_error": cols.scan_error,
            "source_module": "yoke_core.domain.broken",
        }]

    def test_as_db_tuple_returns_column_order(self):
        cols = enrich.EnrichmentColumns(
            line_count=10,
            language="python",
            module_name="x.y",
            area="backend",
            is_generated=0,
            dependency_edges="[]",
        )
        assert enrich.as_db_tuple(cols) == (
            10, "python", "x.y", "backend", 0, "[]",
        )


def _seed_repo(tmp_path, files):
    import subprocess as _sp
    repo = tmp_path / "repo"
    repo.mkdir()
    _sp.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    _sp.run(["git", "config", "user.email", "t@e.com"],
            cwd=repo, check=True)
    _sp.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    for rel, body in files.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    _sp.run(["git", "add", "-A"], cwd=repo, check=True)
    _sp.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    return repo


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class TestWriteEntriesPopulatesSnapshot:
    """``write_entries`` integration via :func:`build_head_snapshot`:
    enrichment columns populate for files; directories carry DDL
    defaults; Python imports surface as ``dependency_edges`` JSON."""

    def test_python_file_carries_enrichment_columns(self, tmp_path):
        from yoke_core.domain.path_snapshots import build_head_snapshot
        repo = _seed_repo(tmp_path, {"src/a.py": "VALUE = 1\n"})
        with path_snapshot_db(tmp_path, repo) as conn:
            snap_id = build_head_snapshot(conn, "demo")
            p = _p(conn)
            row = conn.execute(
                "SELECT e.line_count, e.language, e.module_name, "
                "e.is_generated, e.dependency_edges "
                "FROM path_snapshot_entries e "
                "JOIN path_targets t ON t.id = e.target_id "
                f"WHERE e.snapshot_id = {p} AND t.path_string = {p}",
                (snap_id, "src/a.py"),
            ).fetchone()
            assert tuple(row) == (1, "python", "src.a", 0, "[]")

    def test_python_imports_recorded_as_dependency_edges(self, tmp_path):
        from yoke_core.domain.path_snapshots import build_head_snapshot
        repo = _seed_repo(tmp_path, {
            "pkg/__init__.py": "",
            "pkg/mod.py": "import json\nfrom pkg import other\n",
            "pkg/other.py": "VALUE = 1\n",
        })
        with path_snapshot_db(tmp_path, repo) as conn:
            snap_id = build_head_snapshot(conn, "demo")
            p = _p(conn)
            row = conn.execute(
                "SELECT dependency_edges FROM path_snapshot_entries e "
                "JOIN path_targets t ON t.id = e.target_id "
                f"WHERE e.snapshot_id = {p} AND t.path_string = {p}",
                (snap_id, "pkg/mod.py"),
            ).fetchone()
            edges = json.loads(row[0])
            triples = {(e["source_module"], e["imported_module"],
                        e["imported_name"]) for e in edges}
            assert ("pkg.mod", "json", "json") in triples
            assert ("pkg.mod", "pkg", "other") in triples

    def test_markdown_file_has_language_no_module(self, tmp_path):
        from yoke_core.domain.path_snapshots import build_head_snapshot
        repo = _seed_repo(tmp_path, {"README.md": "hi\n"})
        with path_snapshot_db(tmp_path, repo) as conn:
            snap_id = build_head_snapshot(conn, "demo")
            p = _p(conn)
            row = conn.execute(
                "SELECT e.language, e.module_name, e.dependency_edges "
                "FROM path_snapshot_entries e "
                "JOIN path_targets t ON t.id = e.target_id "
                f"WHERE e.snapshot_id = {p} AND t.path_string = {p}",
                (snap_id, "README.md"),
            ).fetchone()
            assert tuple(row) == ("markdown", None, "[]")

    def test_directory_rows_carry_defaults(self, tmp_path):
        from yoke_core.domain.path_snapshots import build_head_snapshot
        repo = _seed_repo(tmp_path, {"src/a.py": "VALUE = 1\n"})
        with path_snapshot_db(tmp_path, repo) as conn:
            snap_id = build_head_snapshot(conn, "demo")
            p = _p(conn)
            row = conn.execute(
                "SELECT e.line_count, e.language, e.module_name, "
                "e.area, e.is_generated, e.dependency_edges "
                "FROM path_snapshot_entries e "
                "JOIN path_targets t ON t.id = e.target_id "
                f"WHERE e.snapshot_id = {p} AND t.path_string = {p} "
                "AND t.kind = 'directory'",
                (snap_id, "src"),
            ).fetchone()
            assert tuple(row) == (None, None, None, None, 0, "[]")

    def test_write_entries_uses_snapshot_context_cache(
        self, tmp_path, monkeypatch
    ):
        from yoke_core.domain.path_snapshots import build_head_snapshot

        repo = _seed_repo(tmp_path, {
            "src/a.py": "VALUE = 1\n",
            "src/b.py": "VALUE = 2\n",
        })

        def fail_read_context_value(*_args, **_kwargs):
            raise AssertionError("write_entries should use context cache")

        monkeypatch.setattr(
            enrich, "read_context_value", fail_read_context_value,
        )
        with path_snapshot_db(tmp_path, repo) as conn:
            snap_id = build_head_snapshot(conn, "demo")
            count = conn.execute(
                "SELECT COUNT(*) FROM path_snapshot_entries "
                f"WHERE snapshot_id = {_p(conn)}",
                (snap_id,),
            ).fetchone()[0]
            assert count > 0
