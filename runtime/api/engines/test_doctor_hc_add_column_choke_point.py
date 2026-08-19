"""HC-add-column-choke-point: executable lock-taking adds are confined."""

from __future__ import annotations

from pathlib import Path

from yoke_core.api.repo_root import find_repo_root
from yoke_project_checks import check_add_column_choke_point as hc


def _write(root: Path, name: str, body: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_current_tree_has_no_raw_executable_add_column() -> None:
    repo_root = find_repo_root(Path(__file__))
    assert hc.scan_raw_add_column_if_not_exists(repo_root) == []


def test_schema_init_columns_docstring_is_not_a_finding() -> None:
    repo_root = find_repo_root(Path(__file__))
    findings = hc.scan_raw_add_column_if_not_exists(repo_root)
    assert not any("schema_init_columns.py" in row.relpath for row in findings)


def test_detects_executable_raw_occurrence(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/example/schema.py",
        "def apply(conn):\n"
        "    conn.execute(\n"
        '        "ALTER TABLE t ADD COLUMN IF NOT EXISTS c TEXT"\n'
        "    )\n",
    )
    findings = hc.scan_raw_add_column_if_not_exists(tmp_path, roots=["packages"])
    assert [(row.relpath, row.line) for row in findings] == [
        ("packages/example/schema.py", 3)
    ]


def test_docstring_mention_is_out_of_scope(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/example/docs_only.py",
        '"""Contains ONLY ADD COLUMN IF NOT EXISTS and CREATE INDEX."""\n'
        "def apply(conn):\n"
        "    return conn\n",
    )
    assert hc.scan_raw_add_column_if_not_exists(tmp_path, roots=["packages"]) == []


def test_comment_mention_is_out_of_scope(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/example/comment_only.py",
        "# ALTER TABLE t ADD COLUMN IF NOT EXISTS c TEXT\n"
        "def apply(conn):\n"
        "    return conn\n",
    )
    assert hc.scan_raw_add_column_if_not_exists(tmp_path, roots=["packages"]) == []


def test_named_throwaway_fixture_is_exempt(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "runtime/api/merge_worktree_test_db.py",
        'conn.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS x TEXT")\n',
    )
    assert hc.scan_raw_add_column_if_not_exists(tmp_path, roots=["runtime"]) == []


def test_test_modules_are_out_of_scope(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "runtime/api/test_setup.py",
        'conn.execute("ALTER TABLE t ADD COLUMN IF NOT EXISTS c TEXT")\n',
    )
    assert hc.scan_raw_add_column_if_not_exists(tmp_path, roots=["runtime"]) == []


def test_helper_module_is_out_of_scope(tmp_path: Path) -> None:
    _write(
        tmp_path,
        hc.CHOKE_POINT,
        'SQL = "ALTER TABLE t ADD COLUMN IF NOT EXISTS c TEXT"\n',
    )
    assert hc.scan_raw_add_column_if_not_exists(tmp_path, roots=["packages"]) == []
