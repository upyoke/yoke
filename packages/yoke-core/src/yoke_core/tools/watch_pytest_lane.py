"""Bring the lane under ``yoke watch pytest --impacted`` current before selection.

Workers run the impacted selection over and over while they implement, on
every harness, so updating the lane here keeps it on current
``origin/<base>`` with no extra step. The first comparison with the base
then happens while the worker iterates, not at the full-CI gate.

Only a lane is updated: a checkout on its project's base branch or on a
detached HEAD (a CI checkout) runs as it is, and so does a tree no Yoke
project owns. The update itself is :mod:`yoke_core.domain.lane_base_update`,
the same one the full-CI gate runs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_core.tools import _watch_runner

KIND = "pytest"


def _note(progress_capture: Path | None, text: str) -> None:
    _watch_runner.note_claimed_capture(progress_capture, f"# watch_{KIND} lane-update: {text}")


def _current_branch(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "HEAD"


def bring_lane_current(root: Path, progress_capture: Path | None) -> str | None:
    """Update the lane at *root*; return a refusal message, or ``None`` to run.

    A refusal leaves the lane untouched and names the reason and recovery;
    the caller prints it and runs no tests.
    """
    from yoke_core.domain import lane_base_update, qa_case_ci_entry_run
    from yoke_core.domain.project_selection import (
        MissingProjectError,
        required_local_project,
    )

    branch = _current_branch(root)
    if branch == "HEAD":
        _note(progress_capture, "skipped: detached HEAD is not a lane")
        return None
    try:
        project = required_local_project(root)
    except MissingProjectError:
        _note(progress_capture, f"skipped: no Yoke project owns {root}")
        return None
    target = qa_case_ci_entry_run.base_branch(project, root)
    if branch == target:
        _note(progress_capture, f"skipped: {root} is on the base branch {target}")
        return None
    _note(progress_capture, f"bringing {branch} current with origin/{target}")
    try:
        moved = lane_base_update.bring_lane_current(
            root, branch=branch, target=target, project=project
        )
    except lane_base_update.LaneBaseUpdateRefused as exc:
        return f"watch_pytest LANE-UPDATE REFUSAL: {exc}"
    outcome = f"updated onto origin/{target}" if moved else "already current"
    print(f"watch_pytest: lane {branch} {outcome}", flush=True)
    _note(progress_capture, f"{branch} {outcome}")
    return None


__all__ = ["bring_lane_current"]
