"""Pytest argv, env, and impacted selection for a checkout's test environment."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from yoke_contracts.uv_project import is_uv_project, uv_run_argv
from yoke_core.domain.test_environment_declaration import load_declaration
from yoke_core.tools import _source_pythonpath
from yoke_core.tools.impacted_project_test_roots import (
    UNSUPPORTED_PROJECT_TEST_ROOTS,
    resolve_test_roots,
)


def pytest_argv(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
) -> list[str]:
    """Underlying pytest invocation for *cwd* (or the process cwd)."""
    here = (cwd or Path.cwd()).resolve()
    root = _source_pythonpath.repo_root(here)
    if _source_pythonpath.is_yoke_shaped_tree(root) or (
        _source_pythonpath.is_yoke_shaped_tree(here)
    ):
        return [sys.executable, "-m", "pytest", *list(args)]
    declaration = load_declaration(checkout=here)
    trailing = ["-m", "pytest", *list(args)]
    argv = declaration.run_python_argv(trailing, cwd=here)
    # An undeclared selection outside a uv project has no environment to bind,
    # so the console script's own interpreter is the only one that can run.
    if argv == uv_run_argv(trailing) and not is_uv_project(here):
        return [sys.executable, "-m", "pytest", *list(args)]
    return argv


def impacted_selection(base: str, *, bounded: bool = False):
    """Impacted selection, or ``None`` when the project has no test roots."""
    from yoke_core.tools import impacted_tests

    root = _source_pythonpath.repo_root(Path.cwd())
    roots = resolve_test_roots(str(root))
    if not roots:
        print(f"watch_pytest {UNSUPPORTED_PROJECT_TEST_ROOTS}", flush=True)
        return None
    selection = impacted_tests.selection_for(root, base, bounded=bounded)
    scope = "full sweep" if selection.full_sweep else "impacted"
    print(
        f"watch_pytest {scope}: {selection.reason}; {selection.count_summary()}",
        flush=True,
    )
    print(f"watch_pytest {selection.telemetry()}", flush=True)
    return selection if selection.pytest_paths() else None


def selection_footer(selection, collected_items: int | None) -> str:
    all_files = selection.full_sweep or len(selection.files) == selection.total_files
    total_items = collected_items if all_files else None
    counted = replace(
        selection, selected_items=collected_items, total_items=total_items
    )
    return f"# watch_pytest selection-summary: {counted.count_summary()}"


__all__ = [
    "impacted_selection",
    "pytest_argv",
    "selection_footer",
]
