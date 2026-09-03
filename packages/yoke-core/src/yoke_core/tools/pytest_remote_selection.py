"""Where a change-scoped pytest run executes: this machine, or the project's CI.

Six lanes each running their own impacted selection at once turned an
18-core workstation into one that served tool calls at seven times its idle
latency, while the same tests take about a minute on one hosted runner. So
for a project that declares its CI workflow, ``yoke watch pytest`` and the
generic runner behind it execute remotely by default: the lane commit is
pushed, a dedicated selection workflow is dispatched with the commit under
test and the merge base the change is measured against, and the run's
conclusion is adopted as the verdict. The machine runs sessions; CI runs
tests.

This module decides which of three things happens — run here, run on CI,
or refuse with a named reason — and describes a remote run for the engine
in :mod:`yoke_core.tools.pytest_remote_selection_run`. ``--local`` (or the
equivalent environment variable) opts one run out; a project that declares
no workflow, or a tree without the selection workflow file, runs here
without being asked. A dirty tree is refused rather than silently tested
without its edits: CI can only test what was pushed.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from yoke_contracts.project_defaults import default_project_for_directory
from yoke_core.tools._impacted_changed_paths import DEFAULT_BASE_REF

LOCAL_FLAG = "--local"
#: Shell-wide equivalent of ``--local``: every run started under it executes
#: on this machine. The test suite pins it so an in-process wrapper call
#: never publishes the tree it is running inside.
LOCAL_ENV = "YOKE_PYTEST_LOCAL"
#: Optional key in the ``ci_workflow_file`` capability settings naming the
#: selection workflow; absent, the conventional filename below is assumed.
SELECTION_WORKFLOW_KEY = "selection_workflow_file"
DEFAULT_SELECTION_WORKFLOW_FILE = "yoke-tests-selection.yml"
WORKFLOWS_DIR = Path(".github") / "workflows"
ENGINE_MODULE = "yoke_core.tools.pytest_remote_selection_run"
#: Every line the engine narrates starts with this, so a capture reader and
#: the watcher classifier recognise the remote run's own voice.
PREFIX = "remote selection:"

#: Exit statuses. A refusal before anything moves shares the usage status
#: the wrapper gives a doomed invocation; the others mirror the run.
EXIT_REFUSED = 2
EXIT_TIMED_OUT = 3
EXIT_UNREACHABLE = 4
EXIT_CANCELLED = 5

#: pytest arguments that describe this machine rather than the selection.
#: They are dropped from a remote dispatch, and the drop is named.
MACHINE_LOCAL_FLAGS = ("-n", "--numprocesses", "--rootdir")


@dataclass(frozen=True)
class LocalRoute:
    """Run on this machine, and why."""

    reason: str


@dataclass(frozen=True)
class Refusal:
    """Neither route is safe; the message names the reason and the recovery."""

    message: str
    exit_code: int


@dataclass(frozen=True)
class RemoteRoute:
    """One selection run on the project's CI."""

    root: Path
    project: str
    workflow: str
    repo: str
    branch: str
    head_sha: str
    base_sha: str
    pytest_args: tuple[str, ...]
    dropped_args: tuple[str, ...] = ()

    @property
    def dispatch_id(self) -> str:
        """Deterministic per tree and selection.

        The correlated dispatch replays a request id it has seen: a second
        invocation on the same commit with the same arguments rejoins the
        run already in flight (or already concluded) instead of paying for
        a duplicate.
        """
        digest = hashlib.sha256(
            "\0".join((self.base_sha, *self.pytest_args)).encode("utf-8")
        ).hexdigest()[:12]
        return f"watch-pytest:{self.head_sha}:{digest}"

    def engine_argv(self) -> list[str]:
        return [
            sys.executable, "-m", ENGINE_MODULE,
            "--root", str(self.root),
            "--project", self.project,
            "--workflow", self.workflow,
            "--repo", self.repo,
            "--branch", self.branch,
            "--head-sha", self.head_sha,
            "--base-sha", self.base_sha,
            "--dispatch-id", self.dispatch_id,
            "--", *self.pytest_args,
        ]


def _git(root: Path, *args: str, keep_leading_space: bool = False) -> str | None:
    """Run one git command; ``None`` when it fails or cannot start.

    ``keep_leading_space`` preserves column alignment for output whose
    first column is meaningful — porcelain status codes pad an unstaged
    change to a leading blank, and stripping it eats the first character
    of that file's path.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout if keep_leading_space else completed.stdout.strip()


def strip_machine_local_args(
    args: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split *args* into ``(kept, dropped)`` around the machine-local flags."""
    kept: list[str] = []
    dropped: list[str] = []
    skip_next = False
    for token in args:
        if skip_next:
            dropped.append(token)
            skip_next = False
            continue
        flag, separator, _value = token.partition("=")
        if flag in MACHINE_LOCAL_FLAGS:
            dropped.append(token)
            skip_next = not separator
            continue
        kept.append(token)
    return tuple(kept), tuple(dropped)


def dirty_paths(root: Path) -> list[str]:
    """Tracked modifications and untracked files: both feed the local selection."""
    status = _git(
        root,
        "status",
        "--porcelain",
        "--untracked-files=normal",
        keep_leading_space=True,
    )
    if not status:
        return []
    return [line[3:] for line in status.splitlines() if line.strip()]


def selection_workflow(settings: Mapping[str, object]) -> str:
    """The selection workflow the project declared, or the conventional one."""
    return str(settings.get(SELECTION_WORKFLOW_KEY) or DEFAULT_SELECTION_WORKFLOW_FILE)


def _merge_base(root: Path, base: str) -> str | None:
    found = _git(root, "merge-base", base, "HEAD")
    if found is None and "/" not in base:
        found = _git(root, "merge-base", f"origin/{base}", "HEAD")
    return found


def resolve_route(
    root: Path,
    *,
    pytest_args: Sequence[str],
    impacted_base: str | None,
    local: bool = False,
    env: Mapping[str, str] | None = None,
) -> LocalRoute | Refusal | RemoteRoute:
    """Decide where this run executes; every answer names its reason."""
    environ = os.environ if env is None else env
    if local:
        return LocalRoute(f"{LOCAL_FLAG} was passed")
    if environ.get(LOCAL_ENV):
        return LocalRoute(f"{LOCAL_ENV} is set")
    if environ.get("CI"):
        return LocalRoute("already running on CI")
    project = default_project_for_directory(root)
    from yoke_core.domain.yoke_connected_env import load_active

    if load_active() is None:
        # No binding at all is not an outage to wait out: this process was
        # detached from the machine's control plane on purpose (the
        # source-dev runner hides it so a test child cannot inherit
        # administering authority). With no declaration reachable, the
        # honest answer is the same one an undeclared project gets.
        return LocalRoute(
            "this process has no control-plane connection to read a CI "
            "declaration from"
        )
    try:
        from yoke_core.domain.project_ci_workflow import project_ci_workflow_settings

        settings = project_ci_workflow_settings(project)
    except Exception as exc:  # noqa: BLE001 - the reason is relayed, not hidden
        return Refusal(
            f"Error: {PREFIX} could not read project {project}'s CI "
            f"declaration ({exc}); the control plane is unreachable. Re-run "
            f"with {LOCAL_FLAG} to test on this machine.",
            EXIT_UNREACHABLE,
        )
    if not str(settings.get("workflow_file") or "").strip():
        return LocalRoute(f"project {project} declares no ci_workflow_file capability")
    workflow = selection_workflow(settings)
    if not (root / WORKFLOWS_DIR / workflow).is_file():
        return LocalRoute(f"this tree has no {WORKFLOWS_DIR / workflow}")
    from yoke_core.domain.qa_case_ci_lane import repo_slug
    from yoke_core.domain.qa_case_execution import QaCaseExecutionError

    try:
        repo = repo_slug(root)
    except QaCaseExecutionError as exc:
        return LocalRoute(str(exc))
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    base = impacted_base or DEFAULT_BASE_REF
    if branch in ("HEAD", base):
        return Refusal(
            f"Error: {PREFIX} remote runs test a lane branch, and this "
            f"checkout is on {branch}. Check out the item's lane, or re-run "
            f"with {LOCAL_FLAG}.",
            EXIT_REFUSED,
        )
    dirty = dirty_paths(root)
    if dirty:
        shown = ", ".join(dirty[:5])
        if len(dirty) > 5:
            shown += f" (+{len(dirty) - 5} more)"
        return Refusal(
            f"Error: {PREFIX} the tree has uncommitted changes ({shown}); CI "
            "tests the pushed commit, so the run would not cover them. "
            f"Commit, then run; or re-run with {LOCAL_FLAG}.",
            EXIT_REFUSED,
        )
    head = _git(root, "rev-parse", "HEAD")
    if not head:
        return Refusal(f"Error: {PREFIX} cannot resolve HEAD in {root}", EXIT_REFUSED)
    base_sha = ""
    if impacted_base is not None:
        base_sha = _merge_base(root, impacted_base) or ""
        if not base_sha:
            return Refusal(
                f"Error: {PREFIX} no merge base between {impacted_base} and "
                "HEAD; pass a base that shares history, or re-run with "
                f"{LOCAL_FLAG}.",
                EXIT_REFUSED,
            )
    kept, dropped = strip_machine_local_args(pytest_args)
    return RemoteRoute(
        root=root,
        project=project,
        workflow=workflow,
        repo=repo,
        branch=branch,
        head_sha=head,
        base_sha=base_sha,
        pytest_args=kept,
        dropped_args=dropped,
    )


__all__ = [
    "DEFAULT_SELECTION_WORKFLOW_FILE",
    "ENGINE_MODULE",
    "EXIT_CANCELLED",
    "EXIT_REFUSED",
    "EXIT_TIMED_OUT",
    "EXIT_UNREACHABLE",
    "LOCAL_ENV",
    "LOCAL_FLAG",
    "LocalRoute",
    "MACHINE_LOCAL_FLAGS",
    "PREFIX",
    "Refusal",
    "RemoteRoute",
    "SELECTION_WORKFLOW_KEY",
    "WORKFLOWS_DIR",
    "dirty_paths",
    "resolve_route",
    "selection_workflow",
    "strip_machine_local_args",
]
