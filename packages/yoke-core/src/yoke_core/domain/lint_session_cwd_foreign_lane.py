"""Denial text for a write into a worktree lane another session holds.

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
"""

from __future__ import annotations

from yoke_core.domain.lane_occupancy import LaneOccupant

FAILURE_CLASS = "foreign_lane"


def build_denial_message(
    *, offending_target: str, occupant: LaneOccupant,
) -> str:
    """Name the lane, its holder, and the two ways forward."""
    owner = occupant.item_ref or f"item {occupant.item_id}"
    acquire_ref = occupant.item_ref or "PREFIX-N"
    return "\n".join(
        [
            "Refusing a write into a worktree lane held by another "
            "session.",
            "",
            f"  target:  {offending_target}",
            f"  lane:    {occupant.lane_path}",
            f"  owner:   {owner}",
            f"  held by: session {occupant.session_id}",
            "",
            "That lane has a live work claim. Two agents editing one "
            "worktree share its git index, so staged changes from either "
            "land in whichever one commits first.",
            "",
            "Either coordinate with the holding session, or take the "
            "claim yourself once it is free:",
            "",
            f"  yoke claims work acquire --item {acquire_ref} "
            '--reason "<why you are taking over>"',
        ]
    )


__all__ = ["FAILURE_CLASS", "build_denial_message"]
