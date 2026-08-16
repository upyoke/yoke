"""Prove a prepared lane can run its tests, or refuse to call it ready.

A lane whose Python environment was never materialized looks exactly like
a ready one. The failure surfaces later, at the first test command, as an
import error nobody can attribute — the interpreter that happens to be on
PATH has no ``pytest``, or has ``pytest`` and cannot import the project
package the root ``conftest.py`` reaches for. Every session that meets it
spends a diagnosis cycle rediscovering that dependency provisioning was
skipped, because a skip printed one advisory line and returned success.

So preparation materializes the environment from the project's own
lockfile and then proves it, by collecting one trivial test inside the
lane. Collection is the cheap half of a pytest run and exercises exactly
the path that was failing: the interpreter resolves ``pytest``, and
``pytest`` imports the tree's ``conftest.py``, which imports the project.
A lane that cannot pass that proof blocks preparation with the repair
recipe instead of reporting ready.

Discovery covers nested projects because a repository's test surface is
not always its root: a service repository may carry its Python project
under ``services/<name>/`` beside a JavaScript app and an infrastructure
tree, and that service is the surface whose tests run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

from yoke_contracts.uv_project import (
    LOCKFILE_NAME,
    PROJECT_FILE_NAME,
    UV_EXECUTABLE,
    is_uv_project,
)
from yoke_core.domain import runtime_settings
from yoke_core.domain import verification_tree_binding_pytest_startup as _tree_binding

SYNC_TIMEOUT_CONFIG = "worktree_test_environment_sync_timeout_seconds"
DEFAULT_SYNC_TIMEOUT_SECONDS = 600
PROOF_TIMEOUT_CONFIG = "worktree_test_environment_proof_timeout_seconds"
DEFAULT_PROOF_TIMEOUT_SECONDS = 300

#: How far below the lane root a nested project is still discovered.
NESTED_SEARCH_DEPTH = 3

#: Directories that hold vendored or generated trees rather than sources.
SKIPPED_DIRECTORIES = frozenset(
    {".git", ".venv", ".worktrees", "__pycache__", "build", "dist", "node_modules"}
)

PROOF_DIRECTORY_NAME = ".yoke-lane-check"
PROOF_TEST_FILENAME = "test_lane_environment.py"
PROOF_TEST_SOURCE = "def test_lane_environment_ready():\n    assert True\n"

#: How much of a failing command's output the narrative carries. Enough to
#: name the cause, short enough that the recipe below it still gets read.
FAILURE_DETAIL_LINES = 12


@dataclass(frozen=True)
class TestEnvironmentReport:
    """What preparation did to a lane's test environment, and whether it holds."""

    actions: Tuple[str, ...] = ()
    error: str = ""

    @property
    def ready(self) -> bool:
        return not self.error


def _run(cmd: Sequence[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    """Run *cmd*, turning a launch failure into a captured failing result."""
    try:
        return subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd),
            env=_tree_binding.with_binding_evaluated(os.environ),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return subprocess.CompletedProcess(
            list(cmd),
            returncode=1,
            stdout="",
            stderr=f"{cmd[0] if cmd else '<empty>'}: {type(exc).__name__}: {exc}",
        )


def uv_projects(worktree_path: Path) -> List[Path]:
    """Every uv-managed project in *worktree_path*, outermost first.

    A lane root that is itself a project is the whole answer; nothing
    below it needs its own environment. Otherwise the search descends
    :data:`NESTED_SEARCH_DEPTH` levels, and stops descending under a
    project it has already found.
    """
    if is_uv_project(worktree_path):
        return [worktree_path]

    found: List[Path] = []
    for dirpath, dirnames, _filenames in os.walk(worktree_path):
        here = Path(dirpath)
        depth = len(here.relative_to(worktree_path).parts)
        if depth >= NESTED_SEARCH_DEPTH:
            dirnames.clear()
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SKIPPED_DIRECTORIES and not name.startswith(".")
        )
        if here != worktree_path and is_uv_project(here):
            found.append(here)
            dirnames.clear()
    return found


def runs_pytest(project_dir: Path) -> bool:
    """True when *project_dir* carries a pytest surface worth proving."""
    return (project_dir / "conftest.py").is_file() or (
        project_dir / "tests"
    ).is_dir()


def _declaration_for(worktree_path: Path, project: str | None):
    from yoke_core.domain.test_environment_declaration import load_declaration

    return load_declaration(project, checkout=worktree_path)


def provision_test_environment(
    worktree_path: str,
    *,
    project: str | None = None,
) -> TestEnvironmentReport:
    """Materialize and prove every uv project's test environment in a lane.

    Returns a report whose ``error`` is a blocking narrative: preparation
    must surface it rather than report the lane ready. A lane with no
    uv-managed project is nothing this surface owns, and reports ready
    with no actions.
    """
    from yoke_core.domain.test_environment_declaration import (
        SANCTIONED_RUN_SURFACE,
        resolve_uv_projects,
    )

    root = Path(worktree_path)
    declaration = _declaration_for(root, project)
    try:
        resolved = resolve_uv_projects(root, declaration, discover=uv_projects)
    except OSError as exc:
        return TestEnvironmentReport(
            error=f"Could not scan {root} for uv-managed projects: {exc}"
        )
    if isinstance(resolved, str):
        return TestEnvironmentReport(error=resolved)
    projects = resolved
    if not projects:
        return TestEnvironmentReport()
    if shutil.which(UV_EXECUTABLE) is None:
        return TestEnvironmentReport(error=_missing_uv_narrative(projects))

    sync_timeout = runtime_settings.get_seconds(
        SYNC_TIMEOUT_CONFIG, DEFAULT_SYNC_TIMEOUT_SECONDS
    )
    proof_timeout = runtime_settings.get_seconds(
        PROOF_TIMEOUT_CONFIG, DEFAULT_PROOF_TIMEOUT_SECONDS
    )

    extras = ",".join(declaration.extras)
    groups = ",".join(declaration.groups)
    actions: List[str] = [
        (
            f"selection:uv_project={declaration.uv_project or '.'} "
            f"extras={extras} groups={groups}"
        ),
        f"run:{SANCTIONED_RUN_SURFACE}",
    ]
    for project_dir in projects:
        label = _label(root, project_dir)
        synced = _run(declaration.sync_argv(), project_dir, sync_timeout)
        if synced.returncode != 0:
            return TestEnvironmentReport(
                tuple(actions),
                _sync_failure_narrative(project_dir, synced, declaration),
            )
        actions.append(f"environment:synced={label}")
        if not runs_pytest(project_dir):
            continue
        proved = _collect_trivial_test(project_dir, proof_timeout, declaration)
        if proved.returncode != 0:
            return TestEnvironmentReport(
                tuple(actions),
                _proof_failure_narrative(project_dir, proved, declaration),
            )
        actions.append(f"pytest:collected={label}")
    return TestEnvironmentReport(tuple(actions))


def _collect_trivial_test(
    project_dir: Path, timeout: int, declaration
) -> subprocess.CompletedProcess:
    """Collect one trivial test inside *project_dir* using its environment.

    The test file lives in the tree so pytest resolves the project's own
    ``rootdir`` and loads its ``conftest.py`` — the import that was
    failing. It is removed again whatever the outcome, so a lane never
    carries the proof as untracked state.
    """
    proof_dir = project_dir / PROOF_DIRECTORY_NAME
    proof_file = proof_dir / PROOF_TEST_FILENAME
    trailing = [
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "--collect-only",
        "-q",
        f"{PROOF_DIRECTORY_NAME}/{PROOF_TEST_FILENAME}",
    ]
    try:
        proof_dir.mkdir(parents=True, exist_ok=True)
        proof_file.write_text(PROOF_TEST_SOURCE, encoding="utf-8")
        return _run(
            declaration.run_python_argv(trailing, cwd=project_dir),
            project_dir,
            timeout,
        )
    except OSError as exc:
        return subprocess.CompletedProcess(
            [], returncode=1, stdout="", stderr=f"could not write the proof test: {exc}"
        )
    finally:
        shutil.rmtree(proof_dir, ignore_errors=True)


def _label(root: Path, project: Path) -> str:
    """The project's location as a reader of the lane would name it."""
    return "." if project == root else str(project.relative_to(root))


def _detail(completed: subprocess.CompletedProcess) -> str:
    output = (completed.stderr or "") + (completed.stdout or "")
    lines = [line for line in output.splitlines() if line.strip()]
    return "\n".join(f"  {line}" for line in lines[-FAILURE_DETAIL_LINES:])


def _missing_uv_narrative(projects: Sequence[Path]) -> str:
    listing = "\n".join(f"  - {project}" for project in projects)
    return (
        f"Lane test environment cannot be provisioned: '{UV_EXECUTABLE}' is not on "
        f"PATH, and these projects pin their dependencies with it "
        f"({PROJECT_FILE_NAME} beside {LOCKFILE_NAME}):\n"
        f"{listing}\n"
        "Install uv, then re-run preparation:\n"
        "  brew install uv\n"
        "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    )


def _sync_failure_narrative(
    project: Path, completed: subprocess.CompletedProcess, declaration
) -> str:
    argv = " ".join(declaration.sync_argv())
    inspect = ""
    if declaration.selection_flags():
        inspect = f" Inspect the declaration with {declaration.capability_get_recipe()}."
    return (
        f"Lane test environment could not be installed in {project}:\n"
        f"{_detail(completed)}\n"
        "Fix the dependency declaration or lockfile error shown above, then "
        f"re-run preparation. Lane provisioning ran `{argv}`.{inspect}"
    )


def _proof_failure_narrative(
    project: Path, completed: subprocess.CompletedProcess, declaration
) -> str:
    from yoke_core.domain.test_environment_declaration import SANCTIONED_RUN_SURFACE

    argv = " ".join(declaration.sync_argv())
    if declaration.selection_flags():
        present = (
            " Pytest and collection-time imports must be present in that "
            f"selection. Inspect the declaration with "
            f"{declaration.capability_get_recipe()}."
        )
    else:
        present = (
            " Pytest and every collection-time import must be present in "
            "that default `uv sync --frozen` selection."
        )
    return (
        f"Lane test environment is installed but cannot run pytest in {project}:\n"
        f"{_detail(completed)}\n"
        f"Lane provisioning installed `{argv}`.{present} Repair that "
        "declaration, refresh the lockfile, and re-run preparation.\n"
        "Once the lane is ready, run tests through the watcher, which binds "
        "this same environment:\n"
        f"  {SANCTIONED_RUN_SURFACE} <pytest args>"
    )


__all__ = [
    "DEFAULT_PROOF_TIMEOUT_SECONDS",
    "DEFAULT_SYNC_TIMEOUT_SECONDS",
    "PROOF_TIMEOUT_CONFIG",
    "SYNC_TIMEOUT_CONFIG",
    "TestEnvironmentReport",
    "provision_test_environment",
    "runs_pytest",
    "uv_projects",
]
