"""From-import resolution uses the most specific existing module."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain.architecture_context_data import (
    module_to_target_id,
    module_to_target_id_from_index,
)


@pytest.mark.parametrize("layout", ["flat", "package_under_root", "package_is_root"])
@pytest.mark.parametrize("submodule", ["child.py", "child/__init__.py", None])
def test_from_import_prefers_submodule_then_parent(layout, submodule):
    roots = {} if layout == "flat" else {"pkg": (("src", layout),)}
    prefix = {"flat": "pkg", "package_under_root": "src/pkg",
              "package_is_root": "src"}[layout]
    # Insert the parent first: query row order must not decide resolution.
    index = {f"{prefix}/__init__.py": 1}
    if submodule:
        index[f"{prefix}/{submodule}"] = 2
    expected = 2 if submodule else 1
    assert module_to_target_id_from_index(
        index, "pkg", "child", package_roots=roots,
    ) == expected
    with sqlite3.connect(":memory:") as conn:
        conn.execute(
            "CREATE TABLE path_targets "
            "(path_string TEXT, id INTEGER, project_id INTEGER, kind TEXT)"
        )
        conn.executemany(
            "INSERT INTO path_targets VALUES (?, ?, 1, 'file')", index.items(),
        )
        assert module_to_target_id(
            conn, 1, "pkg", "child", package_roots=roots,
        ) == expected


@pytest.mark.parametrize("imported_name", ["", "*"])
def test_plain_and_star_imports_resolve_parent(imported_name):
    assert module_to_target_id_from_index(
        {"pkg/__init__.py": 1, "pkg/child.py": 2},
        "pkg", imported_name, package_roots={},
    ) == 1


def test_missing_module_remains_unresolved():
    assert module_to_target_id_from_index(
        {}, "external", "symbol", package_roots={},
    ) is None
