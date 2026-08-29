"""Denial text for a target inside a worktree lane another session holds.

Kept beside the policy rather than inside it because the refusal has a
different remedy from every other session-cwd denial. A scope mismatch
tells one session it is outside its own authority, and the fix is that
session's alone. This one says two agents are in the same lane, so the
message has to name the other party and hand back an action that
involves them.

It deliberately does NOT suggest stashing or committing. That advice is
addressed to a single author who has dirtied their own tree; told to a
session that has wandered into somebody else's lane it would convert a
refused write into a commit on top of another agent's uncommitted work.

Read-shaped inspection is still refused when policy requires it, but the
body must say *read* and name the shared-object-store recipe through
the main checkout — never label a ``git show`` / ``ls`` as a write.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.lane_occupancy import LaneOccupant
from yoke_core.domain.lint_session_cwd_path_authority import (
    repo_root_from_worktree_path,
)
from yoke_core.domain.lint_session_cwd_repo_command import (
    retarget_foreign_git_read,
)

FAILURE_CLASS = "foreign_lane"


def _payload_is_write(payload: Mapping[str, Any] | None) -> bool:
    if not payload:
        return True
    from yoke_core.domain.lint_lane_main_write_classify import (
        is_write_operation,
    )

    tool_name = str(payload.get("tool_name") or payload.get("toolName") or "")
    return is_write_operation(tool_name, dict(payload))


def build_denial_message(
    *,
    offending_target: str,
    occupant: LaneOccupant,
    payload: Mapping[str, Any] | None = None,
) -> str:
    """Name the lane, its holder, and the two ways forward."""
    owner = occupant.public_ref or f"item {occupant.item_id}"
    acquire_ref = occupant.public_ref or "PREFIX-N"
    is_write = _payload_is_write(payload)
    verb = "write" if is_write else "read"
    lines = [
        f"Refusing a {verb} into a worktree lane held by another session.",
        "",
        f"  target:  {offending_target}",
        f"  lane:    {occupant.lane_path}",
        f"  owner:   {owner}",
        f"  held by: session {occupant.session_id}",
        "",
    ]
    if is_write:
        lines += [
            "That lane has a live work claim. Two agents editing one "
            "worktree share its git index, so staged changes from either "
            "land in whichever one commits first.",
            "",
        ]
    else:
        main = repo_root_from_worktree_path(occupant.lane_path) or ("<main-checkout>")
        runnable = retarget_foreign_git_read(payload, main)
        lines += [
            "That lane has a live work claim. Cross-lane inspection is "
            "refused even when the command is read-only. Inspect objects "
            "through the shared object store from the main checkout:",
            "",
        ]
        if runnable:
            lines += ["Runnable command:", "", f"  {runnable}", ""]
        else:
            lines += [f"  git -C {main} show <rev> --stat", ""]
    lines += [
        "Either coordinate with the holding session, or take the "
        "claim yourself once it is free:",
        "",
        f"  yoke claims work acquire --item {acquire_ref} "
        '--reason "<why you are taking over>"',
    ]
    return "\n".join(lines)


__all__ = ["FAILURE_CLASS", "build_denial_message"]
