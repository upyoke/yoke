"""Deleted modules retain their importer edges during test selection."""

from pathlib import Path

import pytest

from yoke_core.tools._impacted_import_index import (
    bounded_importer_tests,
    build_import_index,
    direct_importer_tests,
    reachable_tests,
)


@pytest.mark.parametrize(
    ("deleted", "module"),
    [
        ("runtime/api/removed.py", "runtime.api.removed"),
        ("packages/yoke-core/src/yoke_core/removed.py", "yoke_core.removed"),
        ("packages/yoke-core/src/yoke_core/removed/__init__.py", "yoke_core.removed"),
    ],
)
def test_deleted_module_selects_direct_and_transitive_importers(
    tmp_path, deleted, module
):
    sources = {
        deleted: "VALUE = 1\n",
        "runtime/api/bridge.py": f"import {module}\n",
        "runtime/api/test_direct.py": f"import {module}\n",
        "runtime/api/test_transitive.py": "from runtime.api import bridge\n",
        "runtime/api/test_unrelated.py": "import pathlib\n",
    }
    for rel, body in sources.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    before = build_import_index(tmp_path)
    (tmp_path / deleted).unlink()
    after = build_import_index(tmp_path)
    assert deleted not in after.module_of

    direct = frozenset({"runtime/api/test_direct.py"})
    all_importers = direct | {"runtime/api/test_transitive.py"}
    for index in (before, after):
        assert direct_importer_tests([deleted], index) == direct
        assert reachable_tests([deleted], index) == all_importers
        assert (
            bounded_importer_tests([deleted], index, total_files=100) == all_importers
        )


def test_deleted_test_is_not_selected_as_a_runnable_path(tmp_path: Path):
    deleted = "runtime/api/test_removed.py"
    index = build_import_index(tmp_path)

    assert direct_importer_tests([deleted], index) == frozenset()
    assert reachable_tests([deleted], index) == set()
    assert bounded_importer_tests([deleted], index, total_files=100) == frozenset()
