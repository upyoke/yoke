"""The collect plugin narrows root collection to the selection, never below it."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.tools import ci_selection_collect as collect


def test_collection_enters_ancestors_and_selected_paths_only() -> None:
    targets = ("runtime/api/tools/test_a.py", "tests/teaching")

    assert collect.admits("runtime", targets)
    assert collect.admits("runtime/api/tools", targets)
    assert collect.admits("runtime/api/tools/test_a.py", targets)
    assert collect.admits("tests/teaching/deep/test_b.py", targets)
    assert not collect.admits("runtime/api/tools/test_ab.py", targets)
    assert not collect.admits("runtime/harness", targets)
    assert not collect.admits("tests/teaching_prototype", targets)


def test_a_node_id_admits_its_whole_file(tmp_path: Path) -> None:
    selection = tmp_path / "selection.txt"
    selection.write_text(
        "suite/test_a.py::test_one\nsuite/test_a.py::test_two\n\nsuite/sub/\n"
    )

    assert collect.read_targets(selection) == ("suite/test_a.py", "suite/sub")


def test_an_empty_selection_refuses_instead_of_collecting_every_root(
    tmp_path: Path,
) -> None:
    selection = tmp_path / "selection.txt"
    selection.write_text("\n")

    with pytest.raises(pytest.UsageError, match="ci_selection_empty"):
        collect.read_targets(selection)


def test_a_missing_selection_file_is_named(tmp_path: Path) -> None:
    with pytest.raises(pytest.UsageError, match="ci_selection_unreadable"):
        collect.read_targets(tmp_path / "absent.txt")
