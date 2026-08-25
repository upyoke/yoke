"""Doctor tree walks survive a tree that changes underneath them."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from yoke_core.engines.doctor_tree_scan import (
    GENERATED_TREE_NAMES,
    iter_tree_files,
    list_directory,
)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def test_directory_removed_mid_walk_does_not_end_the_scan(tmp_path: Path) -> None:
    for name in ("a", "vanishing", "z"):
        _touch(tmp_path / name / f"{name}.py")

    walk = iter_tree_files(tmp_path, "*.py")
    first = next(walk)
    # The walk is suspended inside "a" and has not reached "vanishing" yet,
    # which is exactly the window a parallel test shard deletes a build tree in.
    shutil.rmtree(tmp_path / "vanishing")

    assert first.name == "a.py"
    assert [found.name for found in walk] == ["z.py"]


def test_permission_error_still_stops_the_scan(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "locked").mkdir()
    real_scandir = os.scandir

    def refuse_locked(path):
        if Path(path).name == "locked":
            raise PermissionError(path)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", refuse_locked)

    with pytest.raises(PermissionError):
        list(iter_tree_files(tmp_path, "*.py"))


def test_pruned_directory_names_are_never_entered(monkeypatch, tmp_path: Path) -> None:
    _touch(tmp_path / "build" / "nested" / "copy.py")
    _touch(tmp_path / "src" / "real.py")

    entered: list[str] = []
    real_scandir = os.scandir

    def record_entry(path):
        entered.append(Path(path).name)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", record_entry)
    found = iter_tree_files(tmp_path, "*.py", prune_dir_names=GENERATED_TREE_NAMES)

    assert [path.name for path in found] == ["real.py"]
    assert "build" not in entered


def test_pattern_matches_file_names_case_sensitively(tmp_path: Path) -> None:
    _touch(tmp_path / "Dockerfile.web")
    _touch(tmp_path / "dockerfile.api")

    assert [path.name for path in iter_tree_files(tmp_path, "Dockerfile*")] == [
        "Dockerfile.web"
    ]


def test_every_file_is_yielded_when_no_pattern_is_given(tmp_path: Path) -> None:
    _touch(tmp_path / "notes.md")
    _touch(tmp_path / "nested" / "code.py")

    assert [path.name for path in iter_tree_files(tmp_path)] == ["notes.md", "code.py"]


def test_list_directory_returns_sorted_children(tmp_path: Path) -> None:
    _touch(tmp_path / "b")
    _touch(tmp_path / "a")

    assert [path.name for path in list_directory(tmp_path)] == ["a", "b"]


def test_list_directory_reports_nothing_when_the_directory_vanished(
    tmp_path: Path,
) -> None:
    assert list_directory(tmp_path / "gone") == []
