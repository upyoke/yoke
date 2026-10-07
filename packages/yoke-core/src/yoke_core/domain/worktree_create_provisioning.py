"""The order in which ``create_worktree`` provisions its planned lanes.

Order is this module's whole subject, because one ordering was silently
wrong. A lane's registry row is created before its path is known, and the
path is what makes that row point at something a session can find. Recording
it only after dependency installation meant every install that failed, hung,
or outlived its caller left an active lane row with a NULL path: a lane
nobody could locate, and a preparation that looked like it had never run.

So the sequence is: create every planned git lane, record their paths, and
only then install dependencies, apply harness enablement, and prove the test
environment. Everything after the recording step can fail loudly without
costing the caller the lane it just made.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional, Sequence

from yoke_core.domain.worktree_create_db import persist_item_worktrees
from yoke_core.domain.worktree_create_plan import (
    WorktreeCreationEntry,
    WorktreeCreationPlan,
)
from yoke_core.domain.worktree_deps import install_worktree_deps
from yoke_core.domain.worktree_provision import (
    create_worktree_lane,
    provision_worktree_folder_trust,
    provision_worktree_harness_enablement,
    provision_worktree_test_environment,
    provision_worktree_validation_surfaces,
)


@dataclass
class LaneProvisioningOutcome:
    """What provisioning did, and which lane a failure belongs to.

    ``path`` and ``branch`` describe the lane a caller should report. A
    lane that failed before it existed carries an empty ``path``; one that
    failed after it was created and recorded carries its real path, so the
    refusal names a directory the reader can go look at.
    """

    error: str = ""
    path: str = ""
    branch: str = ""
    created: bool = False
    failed_branch: str = ""


def install_lane_dependencies(
    entry: WorktreeCreationEntry,
    project: str,
    scripts_dir: str,
) -> None:
    """Install one lane's conventional dependencies, best effort.

    Every failure here is a warning rather than a block: the lane exists,
    its path is already recorded, and the blocking readiness proof is
    :func:`provision_worktree_test_environment`.
    """
    try:
        install_exit = install_worktree_deps(
            entry.path,
            project_id=project,
            scripts_dir=scripts_dir,
        )
    except Exception as exc:  # noqa: BLE001 — non-fatal best-effort install
        print(
            f"Warning: dependency install failed for worktree "
            f"'{entry.branch}' (non-fatal)",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
    else:
        if install_exit != 0:
            print(
                f"Warning: dependency install failed for worktree "
                f"'{entry.branch}' (non-fatal)",
                file=sys.stderr,
            )

    provision_worktree_validation_surfaces(entry.path, project)


def provision_planned_lanes(
    plan: WorktreeCreationPlan,
    *,
    item_id: int | str,
    repo_root: str,
    base_branch: str,
    project: str,
    scripts_dir: str,
    db_path: Optional[str],
) -> LaneProvisioningOutcome:
    """Run every planned lane through the ordered provisioning sequence."""
    primary = plan.primary or plan.worktrees[0]
    pending = [entry for entry in plan.worktrees if not entry.preexisting]

    # Step 1 — the git checkouts, and nothing else. Until a lane exists
    # there is no path to record.
    for entry in pending:
        error = create_worktree_lane(entry, repo_root, base_branch)
        if error:
            entry.error = error
            return LaneProvisioningOutcome(
                error=error,
                branch=entry.branch,
                failed_branch=entry.branch,
            )
        entry.created = True

    any_created = any(entry.created for entry in plan.worktrees)

    # Step 2 — record the paths. This is the step that must precede
    # dependency installation; see this module's docstring.
    recording_error = _record_lane_paths(plan.worktrees, item_id, db_path)
    if recording_error:
        return LaneProvisioningOutcome(
            error=recording_error,
            path=primary.path,
            branch=primary.branch,
            created=any_created,
            failed_branch=primary.branch,
        )

    # Step 3 — best-effort provisioning of the lanes just created.
    for entry in pending:
        install_lane_dependencies(entry, project, scripts_dir)

    # Every harness contributes its lane-enablement operations through its
    # manifest. This runs for reused lanes as well as new ones so a lane
    # prepared before an adapter update is repaired on the next preparation.
    for entry in plan.worktrees:
        provision_worktree_harness_enablement(repo_root, entry.path)
        provision_worktree_folder_trust(entry.path)

    # Step 4 — the blocking readiness proof. A lane is ready when its tests
    # can run in it. This runs for reused lanes too, so a lane prepared
    # before this step existed — or one whose environment drifted from the
    # lockfile — is repaired on the next preparation rather than failing at
    # the first test command.
    for entry in plan.worktrees:
        environment_error = provision_worktree_test_environment(
            entry.path, project=project
        )
        if environment_error:
            return LaneProvisioningOutcome(
                error=environment_error,
                path=entry.path,
                branch=entry.branch,
                created=any_created,
                failed_branch=entry.branch,
            )

    return LaneProvisioningOutcome(
        path=primary.path,
        branch=primary.branch,
        created=any_created,
    )


def _record_lane_paths(
    entries: Sequence[WorktreeCreationEntry],
    item_id: int | str,
    db_path: Optional[str],
) -> str:
    """Persist every lane's path, returning a blocking error narrative."""
    try:
        persist_item_worktrees(
            item_id,
            [
                (entry.lane_id, entry.branch, entry.path, entry.lane_role)
                for entry in entries
            ],
            db_path,
        )
    except Exception as exc:  # noqa: BLE001 - preserve physical lane evidence
        return (
            f"worktree provisioning completed but item-lane persistence failed: {exc}"
        )
    return ""


__all__ = [
    "LaneProvisioningOutcome",
    "install_lane_dependencies",
    "provision_planned_lanes",
]
