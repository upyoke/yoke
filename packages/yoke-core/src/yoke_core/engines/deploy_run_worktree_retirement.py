"""Retiring the detached worktrees a self-deploy driver pins its source in.

A self-deploy run freezes its source by adding ``.worktrees/deploy-<run-id>``
as a detached worktree, so the driver reads a tree that a merge landing on the
live checkout cannot move underneath it. Nothing about finishing a run releases
that directory, and because it carries no branch the branch-bearing registry
every lane-retirement path reads (``git_worktree_registry``) never lists it —
so the merged-lane sweep and the worktree-health check both looked straight
past it. They accumulated until a checkout hit ``max_active_worktrees`` and
refused a new item lane, advising a merge that no deploy worktree has.

This module is the retirement those paths were missing. It answers one question
per directory — is the run that pinned this tree over? — and reclaims only the
directories whose run the control plane names as terminal.

Reclaiming is the same two steps the item-lane paths use: the shared residue
policy clears named and project-declared caches (a driver that executed here
left ``__pycache__`` behind, and that is not content), then a non-force
``git worktree remove`` proves the directory holds nothing else. Force is never
used, so a tree holding real work refuses and says what survived.

Every answer short of "terminal" keeps the directory and names why: a run still
open, a status this build does not recognise, an unreachable control plane, a
directory whose run id cannot be read back, and a tree the calling process is
itself executing from. Removing a live run's pinned source would pull the
ground out from under a driver mid-deploy, which is never worth saving one
directory.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.deployment_run_lifecycle import (
    TERMINAL_RUN_STATUSES,
    run_is_open,
    run_is_terminal,
)
from yoke_core.engines.deploy_run_worktree_naming import (
    deploy_run_worktree_paths,
    run_id_for_driver_worktree,
)
from yoke_core.engines.lane_residue_declared_paths import declared_disposable_roots
from yoke_core.engines.merge_worktree_cleanliness import (
    assess_lane_residue,
    clear_lane_residue,
)


RUN_STATUS_FUNCTION_ID = "deployment_runs.get"
# The one expected keep: a caller sweeping just before it pins its own source.
# Named so that caller can stay quiet about it while still reporting the rest.
CURRENT_RUN_PIN_REASON = "pinned source for the current run"

# What one driver worktree turned out to be. Four states rather than a pair of
# booleans, because callers act differently on each: a directory whose run is
# still going is not a finding at all, one whose run is over is either
# reclaimable now or blocked on something a person reads, and a reclaimed one
# is a repair to report.
LANE_RUN_OPEN = "run-open"
LANE_RETIRABLE = "retirable"
LANE_BLOCKED = "blocked"
LANE_RETIRED = "retired"


@dataclass(frozen=True)
class DeployRunLane:
    """One deploy-run driver worktree and what a sweep found or did about it."""

    path: Path
    run_id: str
    state: str
    reason: str = ""

    @property
    def retired(self) -> bool:
        """Whether this call reclaimed the directory."""
        return self.state == LANE_RETIRED

    @property
    def run_is_open(self) -> bool:
        """Whether the run still needs this tree, so it is not a finding."""
        return self.state == LANE_RUN_OPEN


def _executing_inside(candidate: Path) -> bool:
    """Whether this process is running from inside *candidate*.

    A driver re-executes itself out of its own pinned tree, so a sweep that
    ran there would be deleting the code it is executing. Cheap to ask, and
    the answer is a refusal rather than a crash halfway through.
    """
    probes: list[Path] = [Path(__file__).resolve()]
    for raw in (sys.executable, sys.argv[0] if sys.argv else ""):
        if raw:
            probes.append(Path(raw).resolve())
    try:
        probes.append(Path.cwd().resolve())
    except OSError:
        # A deleted cwd cannot be inside anything we are about to remove.
        pass
    for probe in probes:
        if probe == candidate or probe.is_relative_to(candidate):
            return True
    return False


def _run_status(run_id: str) -> tuple[str, str]:
    """``(status, refusal)`` for *run_id*; refusal set when it cannot be read."""
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    try:
        response = call_dispatcher(
            function_id=RUN_STATUS_FUNCTION_ID,
            target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
            payload={},
        )
    except Exception as exc:  # noqa: BLE001 - unreachable authority == keep it
        return "", f"{RUN_STATUS_FUNCTION_ID} was unreachable ({exc})"
    if not response.success:
        message = (
            response.error.message if response.error is not None else "request refused"
        )
        return "", f"{RUN_STATUS_FUNCTION_ID} refused ({message})"
    run = (response.result or {}).get("run")
    if not isinstance(run, dict):
        return "", f"{RUN_STATUS_FUNCTION_ID} served no run row"
    return str(run.get("status") or ""), ""


def _lane(path: Path, run_id: str, state: str, reason: str = "") -> DeployRunLane:
    return DeployRunLane(path, run_id, state, reason)


def _run_state(run_id: str) -> tuple[str, str]:
    """``(state, reason)`` for the run behind one driver worktree.

    Only a status the vocabulary contract names as terminal reads as finished.
    An empty, unrecognised, or unreadable status is blocked rather than open,
    because it is a leftover somebody has to look at — reporting it as open
    would hide it behind a run that is not actually going anywhere.
    """
    status, refusal = _run_status(run_id)
    if refusal:
        return LANE_BLOCKED, f"run status unreadable: {refusal}"
    if not status:
        return LANE_BLOCKED, "run status is empty"
    if run_is_open(status):
        return LANE_RUN_OPEN, f"run is {status}"
    if not run_is_terminal(status):
        return (
            LANE_BLOCKED,
            f"run status {status!r} is not one of "
            f"{', '.join(TERMINAL_RUN_STATUSES)} and not a known open status",
        )
    return LANE_RETIRABLE, ""


def assess_deploy_run_worktrees(
    *,
    repo_root: str | Path,
    run_git: Callable[..., Any] | None = None,
    keep_run_ids: tuple[str, ...] = (),
) -> tuple[DeployRunLane, ...]:
    """Classify every driver worktree here without changing anything.

    *keep_run_ids* holds the runs the caller is about to use, so a driver
    assessing just before it pins its own source never proposes reclaiming the
    directory it is one step from writing into.

    An unreadable worktree list returns empty: nothing is known, so nothing is
    claimed about this checkout.
    """
    git = run_git or _runtime_git()
    root = Path(repo_root).resolve()
    candidates = deploy_run_worktree_paths(git, root)
    if candidates is None:
        return ()
    declared_roots = declared_disposable_roots(root)
    kept = {run.strip() for run in keep_run_ids if run and run.strip()}

    found: list[DeployRunLane] = []
    for path in candidates:
        run_id = run_id_for_driver_worktree(path, root)
        if run_id in kept:
            found.append(_lane(path, run_id, LANE_RUN_OPEN, CURRENT_RUN_PIN_REASON))
            continue
        if _executing_inside(path):
            found.append(
                _lane(
                    path,
                    run_id,
                    LANE_BLOCKED,
                    "this process is executing from inside it",
                )
            )
            continue
        state, reason = _run_state(run_id)
        if state is not LANE_RETIRABLE:
            found.append(_lane(path, run_id, state, reason))
            continue
        residue = assess_lane_residue(git, path, declared_roots)
        if not residue.disposable:
            found.append(_lane(path, run_id, LANE_BLOCKED, residue.reason))
            continue
        found.append(_lane(path, run_id, LANE_RETIRABLE))
    return tuple(found)


def retire_terminal_deploy_run_worktrees(
    *,
    repo_root: str | Path,
    run_git: Callable[..., Any] | None = None,
    keep_run_ids: tuple[str, ...] = (),
) -> tuple[DeployRunLane, ...]:
    """Reclaim every driver worktree whose run is over; report the rest.

    Returns one :class:`DeployRunLane` per driver worktree found, carrying what
    happened to it, so a caller can show both what it reclaimed and what it
    left rather than burying either.
    """
    git = run_git or _runtime_git()
    root = Path(repo_root).resolve()
    declared_roots = declared_disposable_roots(root)

    verdicts: list[DeployRunLane] = []
    for lane in assess_deploy_run_worktrees(
        repo_root=root, run_git=git, keep_run_ids=keep_run_ids
    ):
        if lane.state != LANE_RETIRABLE:
            verdicts.append(lane)
            continue
        # Clearing named caches is what lets the non-force remove succeed: a
        # driver that executed here left __pycache__ behind, and that is not
        # content. Anything the shared policy will not name stays, and takes
        # the directory with it.
        residue = clear_lane_residue(git, lane.path, declared_roots)
        if not residue.disposable:
            verdicts.append(
                _lane(lane.path, lane.run_id, LANE_BLOCKED, residue.reason)
            )
            continue
        removed = git(
            ["worktree", "remove", str(lane.path)], cwd=str(root), capture=True
        )
        if removed.returncode != 0:
            verdicts.append(
                _lane(
                    lane.path,
                    lane.run_id,
                    LANE_BLOCKED,
                    f"removal refused: {_first_line(removed)}",
                )
            )
            continue
        verdicts.append(_lane(lane.path, lane.run_id, LANE_RETIRED))
    return tuple(verdicts)


def _runtime_git() -> Callable[..., Any]:
    from yoke_core.engines._merge_worktree_runtime import _run_git

    return _run_git


def _first_line(result: Any) -> str:
    from yoke_core.engines.git_worktree_registry import first_output_line

    return first_output_line(result)


__all__ = [
    "CURRENT_RUN_PIN_REASON",
    "LANE_BLOCKED",
    "LANE_RETIRABLE",
    "LANE_RETIRED",
    "LANE_RUN_OPEN",
    "DeployRunLane",
    "RUN_STATUS_FUNCTION_ID",
    "assess_deploy_run_worktrees",
    "retire_terminal_deploy_run_worktrees",
]
