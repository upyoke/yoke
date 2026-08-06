"""HC-ambient-authority-connection-guard: no undeclared raw ambient connects."""

from __future__ import annotations

from pathlib import Path

from yoke_core.api.repo_root import find_repo_root
from yoke_project_checks import check_ambient_authority_connection_guard as hc


def _write(root: Path, name: str, body: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_current_tree_declares_every_raw_ambient_connection() -> None:
    repo_root = find_repo_root(Path(__file__))
    assert hc.scan_for_unguarded_connections(repo_root) == []


def test_detects_the_composition_that_bypasses_the_factory(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "bypass.py",
        "import psycopg\n"
        "from yoke_core.domain import db_backend\n"
        "conn = psycopg.connect(db_backend.resolve_pg_dsn())\n",
    )
    findings = hc.scan_for_unguarded_connections(tmp_path, roots=["."])
    assert [(f.relpath, f.line) for f in findings] == [("bypass.py", 3)]


def test_declared_exemption_clears_the_finding(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "declared.py",
        "import psycopg\n"
        "from yoke_contracts.control_plane_locality import local_authority_exempt\n"
        "from yoke_core.domain import db_backend\n"
        "def open_it():\n"
        "    with local_authority_exempt():\n"
        "        return psycopg.connect(db_backend.resolve_pg_dsn())\n",
    )
    assert hc.scan_for_unguarded_connections(tmp_path, roots=["."]) == []


def test_a_declaration_elsewhere_in_the_file_does_not_cover_a_bare_call(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "mixed.py",
        "import psycopg\n"
        "from yoke_contracts.control_plane_locality import local_authority_exempt\n"
        "from yoke_core.domain import db_backend\n"
        "def declared():\n"
        "    with local_authority_exempt():\n"
        "        return psycopg.connect(db_backend.resolve_pg_dsn())\n"
        "def undeclared():\n"
        "    return psycopg.connect(db_backend.resolve_pg_dsn())\n",
    )
    findings = hc.scan_for_unguarded_connections(tmp_path, roots=["."])
    assert [(f.relpath, f.line) for f in findings] == [("mixed.py", 8)]


def test_explicit_dsn_is_not_an_ambient_acquisition(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "explicit.py",
        "import psycopg\nconn = psycopg.connect(maintenance_dsn())\n",
    )
    assert hc.scan_for_unguarded_connections(tmp_path, roots=["."]) == []


def test_bare_imported_connect_is_matched(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "bare_import.py",
        "from psycopg import connect\n"
        "from yoke_core.domain.db_backend import resolve_pg_dsn\n"
        "conn = connect(resolve_pg_dsn())\n",
    )
    findings = hc.scan_for_unguarded_connections(tmp_path, roots=["."])
    assert [f.relpath for f in findings] == ["bare_import.py"]


def test_a_same_named_connect_on_another_module_is_not_the_driver(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "other.py",
        "import sqlite3\n"
        "from yoke_core.domain import db_backend\n"
        "conn = sqlite3.connect(db_backend.resolve_pg_dsn())\n",
    )
    assert hc.scan_for_unguarded_connections(tmp_path, roots=["."]) == []


def test_test_modules_are_out_of_scope(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "test_thing.py",
        "import psycopg\n"
        "from yoke_core.domain import db_backend\n"
        "conn = psycopg.connect(db_backend.resolve_pg_dsn())\n",
    )
    assert hc.scan_for_unguarded_connections(tmp_path, roots=["."]) == []


def test_generated_build_trees_are_out_of_scope(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/example/build/lib/example/bypass.py",
        "import psycopg\n"
        "from yoke_core.domain import db_backend\n"
        "conn = psycopg.connect(db_backend.resolve_pg_dsn())\n",
    )
    assert hc.scan_for_unguarded_connections(tmp_path, roots=["packages"]) == []
