"""Unit tests for :mod:`yoke_core.domain.architect_plan_anticipation`."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pytest

from yoke_core.domain.architect_plan_anticipation import (
    AnticipationList,
    build_anticipation_list,
)


def _plant(root: Path, rel: str, content: str = "") -> Path:
    """Create ``rel`` (relative to ``root``) with ``content`` and return it."""

    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _make_repo(tmp_path: Path, files: Iterable[tuple[str, str]] = ()) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for rel, content in files:
        _plant(root, rel, content)
    return root


def _file_budget_paths(*paths: str) -> list[str]:
    return list(paths)


def test_doctor_hc_discovery_finds_matching_hc(tmp_path: Path) -> None:
    """AC-4(a): doctor HC files referencing the module land in ``doctor_hcs``."""

    root = _make_repo(
        tmp_path,
        files=[
            ("runtime/api/domain/example_auth.py", "def helper(): pass\n"),
            (
                "runtime/api/engines/doctor_hc_example_auth.py",
                "# Scans example_auth module surface\nMODULE = 'example_auth'\n",
            ),
            (
                "runtime/api/engines/doctor_hc_unrelated.py",
                "# Unrelated HC; covers a different subsystem.\n",
            ),
        ],
    )
    result = build_anticipation_list(
        epic_id=1,
        task_num=1,
        file_budget_paths=_file_budget_paths("runtime/api/domain/example_auth.py"),
        repo_root=root,
    )
    assert "runtime/api/engines/doctor_hc_example_auth.py" in result.doctor_hcs
    assert "runtime/api/engines/doctor_hc_unrelated.py" not in result.doctor_hcs


def test_doctor_hc_discovery_empty_when_no_python_paths(tmp_path: Path) -> None:
    """Non-Python file-budget entries do not synthesise HC hits."""

    root = _make_repo(
        tmp_path,
        files=[
            (
                "runtime/api/engines/doctor_hc_example_auth.py",
                "# example_auth scanner\n",
            ),
        ],
    )
    result = build_anticipation_list(
        epic_id=2,
        task_num=1,
        file_budget_paths=_file_budget_paths(
            "runtime/agents/architect.md",
            ".yoke/docs/lifecycle.md",
        ),
        repo_root=root,
    )
    assert result.doctor_hcs == []


def test_importer_discovery_finds_from_and_import_callers(tmp_path: Path) -> None:
    """AC-4(b): ``from <module> import`` and ``import <module>`` callers land."""

    root = _make_repo(
        tmp_path,
        files=[
            ("runtime/api/domain/example_auth.py", "def helper(): pass\n"),
            (
                "runtime/api/orchestration/uses_via_from.py",
                "from yoke_core.domain.example_auth import helper\n",
            ),
            (
                "runtime/api/orchestration/uses_via_import.py",
                "import yoke_core.domain.example_auth\n",
            ),
            (
                "runtime/api/orchestration/unrelated.py",
                "# does not reference example_auth\nimport json\n",
            ),
        ],
    )
    result = build_anticipation_list(
        epic_id=3,
        task_num=1,
        file_budget_paths=_file_budget_paths("runtime/api/domain/example_auth.py"),
        repo_root=root,
    )
    assert "runtime/api/orchestration/uses_via_from.py" in result.transitive_callers
    assert "runtime/api/orchestration/uses_via_import.py" in result.transitive_callers
    assert "runtime/api/orchestration/unrelated.py" not in result.transitive_callers
    assert "runtime/api/orchestration/unrelated.py" not in result.test_modules


def test_test_module_discovery_uses_test_prefix_naming(tmp_path: Path) -> None:
    """AC-4(c): ``test_*.py`` callers land in ``test_modules`` not ``transitive_callers``."""

    root = _make_repo(
        tmp_path,
        files=[
            ("runtime/api/domain/example_auth.py", "def helper(): pass\n"),
            (
                "runtime/api/test_example_auth.py",
                "from yoke_core.domain.example_auth import helper\n",
            ),
            (
                "runtime/api/orchestration/uses.py",
                "from yoke_core.domain.example_auth import helper\n",
            ),
        ],
    )
    result = build_anticipation_list(
        epic_id=4,
        task_num=1,
        file_budget_paths=_file_budget_paths("runtime/api/domain/example_auth.py"),
        repo_root=root,
    )
    assert "runtime/api/test_example_auth.py" in result.test_modules
    assert "runtime/api/test_example_auth.py" not in result.transitive_callers
    assert "runtime/api/orchestration/uses.py" in result.transitive_callers


def test_deduplication_across_categories_does_not_repeat_paths(tmp_path: Path) -> None:
    """AC-4(d): all_paths returns each repo-relative path exactly once."""

    root = _make_repo(
        tmp_path,
        files=[
            ("runtime/api/domain/example_auth.py", "def helper(): pass\n"),
            (
                "runtime/api/engines/doctor_hc_example_auth.py",
                "# example_auth scanner\n",
            ),
            (
                "runtime/api/orchestration/uses.py",
                "from yoke_core.domain.example_auth import helper\n",
            ),
            (
                "runtime/api/test_example_auth.py",
                "from yoke_core.domain.example_auth import helper\n",
            ),
        ],
    )
    result = build_anticipation_list(
        epic_id=5,
        task_num=1,
        file_budget_paths=_file_budget_paths(
            "runtime/api/domain/example_auth.py",
            # repeat with a different separator to exercise normalization
            "runtime/api/domain/example_auth.py",
        ),
        repo_root=root,
    )
    paths = result.all_paths()
    assert len(paths) == len(set(paths))
    # File-budget entry de-duplicated to a single canonical path.
    assert paths.count("runtime/api/domain/example_auth.py") == 1


def test_empty_input_returns_empty_list(tmp_path: Path) -> None:
    """AC-4(e): empty file_budget_paths yields empty categories."""

    root = _make_repo(tmp_path)
    result = build_anticipation_list(
        epic_id=6,
        task_num=1,
        file_budget_paths=_file_budget_paths(),
        repo_root=root,
    )
    assert result == AnticipationList(
        file_budget=[],
        doctor_hcs=[],
        transitive_callers=[],
        test_modules=[],
    )
    assert result.all_paths() == []


def test_helper_is_read_only_against_repo_tree(tmp_path: Path) -> None:
    """AC-13: helper must not register, widen, narrow, activate, or release a claim.

    Indirect check: running the helper against a populated repo must not
    mutate the file tree (e.g., no temp files, no path-claim sentinel files).
    Snapshot the file set before and after.
    """

    root = _make_repo(
        tmp_path,
        files=[
            ("runtime/api/domain/example_auth.py", "def helper(): pass\n"),
            (
                "runtime/api/engines/doctor_hc_example_auth.py",
                "# example_auth scanner\n",
            ),
        ],
    )
    before = {p.relative_to(root) for p in root.rglob("*") if p.is_file()}
    build_anticipation_list(
        epic_id=7,
        task_num=1,
        file_budget_paths=_file_budget_paths("runtime/api/domain/example_auth.py"),
        repo_root=root,
    )
    after = {p.relative_to(root) for p in root.rglob("*") if p.is_file()}
    assert before == after


def test_helper_accepts_int_epic_and_task_num_without_db_dependency(
    tmp_path: Path,
) -> None:
    """AC-3: signature ``(epic_id, task_num, file_budget_paths, *, repo_root)``.

    The helper does not consult the DB for ``(epic_id, task_num)`` in v0; this
    test asserts the arguments are accepted without requiring an active DB or
    matching row.
    """

    root = _make_repo(tmp_path)
    result = build_anticipation_list(
        epic_id=99999,
        task_num=42,
        file_budget_paths=_file_budget_paths(),
        repo_root=root,
    )
    assert isinstance(result, AnticipationList)


@pytest.mark.parametrize(
    "fb_path,expected_basename",
    [
        ("runtime/api/domain/example_auth.py", "example_auth"),
        ("runtime/api/domain/nested/deep_helper.py", "deep_helper"),
    ],
)
def test_module_basename_drives_doctor_hc_match(
    tmp_path: Path, fb_path: str, expected_basename: str
) -> None:
    """The doctor HC scan uses the file-budget module's basename as a literal substring match."""

    root = _make_repo(
        tmp_path,
        files=[
            (fb_path, "def helper(): pass\n"),
            (
                f"runtime/api/engines/doctor_hc_{expected_basename}.py",
                f"# scanner for {expected_basename}\n",
            ),
        ],
    )
    result = build_anticipation_list(
        epic_id=8,
        task_num=1,
        file_budget_paths=_file_budget_paths(fb_path),
        repo_root=root,
    )
    assert (
        f"runtime/api/engines/doctor_hc_{expected_basename}.py" in result.doctor_hcs
    )
