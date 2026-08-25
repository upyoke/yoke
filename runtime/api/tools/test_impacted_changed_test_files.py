"""Changed and added test files are always part of impacted selection."""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_core.tools import impacted_tests
from yoke_core.tools._impacted_changed_paths import (
    changed_paths,
    normalize_changed_path,
)
from yoke_core.tools.impacted_tests import (
    build_import_index,
    select,
    selection_for,
)

from runtime.api.tools.test_impacted_tests import _tiny_repo, _with_floor, _write


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _git_init(repo: Path, *, branch: str = "main") -> None:
    _git(repo, "init", "-b", branch)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _commit_tree(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def test_normalize_changed_path_strips_dot_slash_and_quotes() -> None:
    assert normalize_changed_path('  "./runtime/api/test_new.py"  ') == (
        "runtime/api/test_new.py"
    )


def test_bounded_near_total_remainder_keeps_changed_test_files(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, "runtime/api/foundation.py", "VALUE = 1\n")
    changed_test = "runtime/api/test_foundation_0.py"
    for number in range(impacted_tests.MIN_EFFECTIVELY_FULL_FILE_UNIVERSE):
        _write(
            root,
            f"runtime/api/test_foundation_{number}.py",
            "from runtime.api import foundation\n",
        )

    bounded = select(
        ["runtime/api/foundation.py", changed_test],
        build_import_index(root),
        bounded=True,
    )

    assert bounded.bounded_deferral is True
    assert changed_test in bounded.files


def test_branch_adding_a_new_test_file_always_selects_it(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    _git_init(root)
    _commit_tree(root, "base")
    _git(root, "checkout", "-b", "item")
    added = "runtime/api/test_added_on_branch.py"
    _write(root, added, "def test_added():\n    pass\n")
    _commit_tree(root, "add test")

    selection = selection_for(root, "main", bounded=True)

    assert added in changed_paths(root, "main")
    assert added in selection.files
    assert selection.files == _with_floor(added)


def test_changed_paths_falls_back_to_origin_base_when_local_base_is_missing(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    origin = tmp_path / "origin.git"
    _tiny_repo(checkout)
    _git_init(checkout)
    _commit_tree(checkout, "base")
    subprocess.run(
        ["git", "clone", "--bare", str(checkout), str(origin)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(checkout, "checkout", "-b", "item")
    added = "runtime/api/test_added_on_branch.py"
    _write(checkout, added, "def test_added():\n    pass\n")
    _commit_tree(checkout, "add test")
    _git(checkout, "branch", "-D", "main")
    _git(checkout, "remote", "add", "origin", str(origin))
    _git(checkout, "fetch", "origin")

    selection = selection_for(checkout, "main", bounded=True)

    assert added in changed_paths(checkout, "main")
    assert added in selection.files
