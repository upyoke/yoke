"""Source-closure digest tests for portable governed migrations."""

from __future__ import annotations

import hashlib

import pytest

from yoke_core.domain.migration_source_digest import (
    MigrationSourceDigestError,
    migration_source_digest,
    migration_source_files,
)


def test_source_without_local_migration_import_keeps_raw_digest(tmp_path) -> None:
    source = tmp_path / "standalone.py"
    source.write_text("def apply(conn):\n    return conn\n", encoding="utf-8")

    assert migration_source_files(source) == (source.resolve(),)
    assert (
        migration_source_digest(source)
        == hashlib.sha256(source.read_bytes()).hexdigest()
    )


def test_recursive_local_imports_are_bound_and_drift_invalidates_digest(
    tmp_path,
) -> None:
    root = tmp_path / "root.py"
    helper = tmp_path / "helper.py"
    leaf = tmp_path / "leaf.py"
    root.write_text(
        "from yoke_core.domain.migrations.helper import run\n"
        "def apply(conn):\n"
        "    return run(conn)\n",
        encoding="utf-8",
    )
    helper.write_text(
        "from yoke_core.domain.migrations.leaf import finish\n"
        "def run(conn):\n"
        "    return finish(conn)\n",
        encoding="utf-8",
    )
    leaf.write_text("def finish(conn):\n    return conn\n", encoding="utf-8")

    before = migration_source_digest(root)
    assert {path.name for path in migration_source_files(root)} == {
        "helper.py",
        "leaf.py",
        "root.py",
    }

    leaf.write_text(
        "def finish(conn):\n    return (conn, 'changed')\n", encoding="utf-8"
    )

    assert migration_source_digest(root) != before


@pytest.mark.parametrize(
    "import_line",
    [
        "from . import helper",
        "from yoke_core.domain.migrations import helper",
    ],
)
def test_local_import_from_package_binds_named_module(tmp_path, import_line) -> None:
    root = tmp_path / "root.py"
    helper = tmp_path / "helper.py"
    root.write_text(f"{import_line}\n", encoding="utf-8")
    helper.write_text("VALUE = 1\n", encoding="utf-8")

    assert {path.name for path in migration_source_files(root)} == {
        "helper.py",
        "root.py",
    }


def test_missing_local_migration_dependency_refuses_digest(tmp_path) -> None:
    source = tmp_path / "root.py"
    source.write_text(
        "from yoke_core.domain.migrations.missing import run\n",
        encoding="utf-8",
    )

    with pytest.raises(MigrationSourceDigestError, match="dependency is missing"):
        migration_source_digest(source)
