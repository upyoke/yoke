"""Pytest argv, env, and impacted selection for a checkout's test environment."""

from __future__ import annotations

from yoke_core.domain import verification_tree_binding
from yoke_core.tools import impacted_tests

from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from typing import Sequence

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.uv_project import is_uv_project, uv_run_argv
from yoke_core.domain.qa_environment_declaration import load_declaration
from yoke_core.domain import source_python_environment
import os
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
        binding = source_python_environment.resolve(root, os.environ)
        return [binding.python, "-m", "pytest", *list(args)]
    declaration = load_declaration(checkout=here)
    trailing = ["-m", "pytest", *list(args)]
    argv = declaration.run_python_argv(trailing, cwd=here)
    # Reuse an active checkout environment before looking for its root .venv.
    if argv == uv_run_argv(trailing) and not is_uv_project(here):
        if sys.prefix != sys.base_prefix and Path(sys.prefix).resolve().is_relative_to(
            root.resolve()
        ):
            return [sys.executable, *trailing]
        return [str(_checkout_venv_python(root)), *trailing]
    return argv


def _checkout_venv_python(root: Path) -> Path:
    """The repo root's own .venv interpreter, or a refusal naming its setup."""
    prefix = root / ".venv"
    python = source_python_environment.venv_python(prefix)
    if python.is_file():
        return python
    raise source_python_environment.SourceEnvironmentRefusal(
        compose_refusal(
            f"PROJECT-ENVIRONMENT-MISSING: no project environment at {prefix}; "
            "this checkout is not a uv project and declares no test environment, "
            "and Yoke's own interpreter does not carry the project's test packages.",
            recovery=(
                "Set the project's setup_command capability to a command that "
                "creates .venv with pytest and the project's test dependencies, "
                "for example `yoke projects capability settings merge "
                "--project PROJECT --cap-type setup_command --set "
                "'command=python3 -m venv .venv && .venv/bin/pip install -e . "
                "pytest'`; run that command in "
                f"{root}, then retry. A uv project (pyproject.toml beside "
                "uv.lock) declares the test_environment capability instead"
            ),
        )
    )


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
