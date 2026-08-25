"""Pytest argv, env, and impacted selection for a checkout's test environment."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
import subprocess
from typing import Sequence

from yoke_contracts.uv_project import is_uv_project, uv_run_argv
from yoke_core.domain.qa_environment_declaration import load_declaration
from yoke_core.tools import _source_pythonpath
from yoke_core.tools.impacted_project_test_roots import (
    UNSUPPORTED_PROJECT_TEST_ROOTS,
    resolve_test_roots,
)


BOUNDED_DEFERRAL_VERDICT = "FULL COVERAGE DEFERRED TO FINAL QA GATE"


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


def _git_common_dir(checkout: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode or not completed.stdout.strip():
        return ""
    common = Path(completed.stdout.strip())
    return str((common if common.is_absolute() else checkout / common).resolve())


def impacted_tree(cwd: Path | None = None) -> Path:
    """Resolve one impacted run to its unique same-repository claimed lane."""
    invocation = _source_pythonpath.repo_root(cwd or Path.cwd()).resolve()
    from yoke_core.domain import verification_tree_binding

    session_id = verification_tree_binding.ambient_session_id()
    if not session_id:
        return invocation
    lookup = verification_tree_binding.resolve_claim_worktrees(session_id)
    repository = _git_common_dir(invocation)
    if not lookup.reachable or not repository:
        return invocation
    candidates: list[Path] = []
    for raw_path in lookup.worktrees:
        path = Path(raw_path).resolve()
        if not path.is_dir() or _git_common_dir(path) != repository:
            continue
        root = _source_pythonpath.repo_root(path).resolve()
        if root not in candidates:
            candidates.append(root)
    if invocation in candidates:
        return invocation
    return candidates[0] if len(candidates) == 1 else invocation


def impacted_selection(
    base: str,
    *,
    bounded: bool = False,
    root: Path | None = None,
):
    """Impacted selection, or ``None`` when the project has no test roots."""
    from yoke_core.tools import impacted_tests

    checkout = (root or impacted_tree()).resolve()
    roots = resolve_test_roots(str(checkout))
    if not roots:
        print(f"watch_pytest {UNSUPPORTED_PROJECT_TEST_ROOTS}", flush=True)
        return None
    selection = impacted_tests.selection_for(checkout, base, bounded=bounded)
    scope = "full sweep" if selection.full_sweep else "impacted"
    print(
        f"watch_pytest {scope}: {selection.reason}; {selection.count_summary()}",
        flush=True,
    )
    print(f"watch_pytest {selection.telemetry()}", flush=True)
    return selection if selection.pytest_paths() else None


def _selection_verdict_prefix(selection) -> str:
    if selection.bounded_deferral:
        return f"{BOUNDED_DEFERRAL_VERDICT}; "
    return ""


def selection_progress_banner(selection) -> str:
    """Prominent start-of-stream selection verdict and telemetry."""
    return (
        "# watch_pytest selection-start: "
        f"{_selection_verdict_prefix(selection)}{selection.telemetry()}"
    )


def selection_footer(selection, collected_items: int | None) -> str:
    all_files = selection.full_sweep or len(selection.files) == selection.total_files
    total_items = collected_items if all_files else None
    counted = replace(
        selection, selected_items=collected_items, total_items=total_items
    )
    return (
        "# watch_pytest selection-summary: "
        f"{_selection_verdict_prefix(counted)}{counted.telemetry()}"
    )


__all__ = [
    "BOUNDED_DEFERRAL_VERDICT",
    "impacted_selection",
    "impacted_tree",
    "pytest_argv",
    "selection_footer",
    "selection_progress_banner",
]
