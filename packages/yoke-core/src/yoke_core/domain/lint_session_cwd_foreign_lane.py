"""The foreign-lane rule: what a held lane accepts, and how it refuses.

Kept beside the policy rather than inside it because this refusal has a
different remedy from every other session-cwd denial. A scope mismatch
tells one session it is outside its own authority, and the fix is that
session's alone. This one says two agents are in the same lane, so the
message has to name the other party and hand back an action that
involves them.

Read-only Git inspection of a held lane is allowed. A worker told to
survey the neighbour it shares a file with needs ``git status`` and
``git diff`` against the neighbour's tree, and refusing those left the
survey with no executable recipe. Everything that writes or moves state
stays refused, so the allowance is a positive classification of one
plain Git call rather than an absence of write evidence: a redirect, a
chained command, a substitution, or an ``--output`` file each drop the
call back to refused.

The refusal deliberately does NOT suggest stashing or committing. That
advice is addressed to a single author who has dirtied their own tree;
told to a session that has wandered into somebody else's lane it would
convert a refused write into a commit on top of another agent's
uncommitted work.
"""

from __future__ import annotations

import shlex
from typing import Any, List, Mapping, Sequence

from yoke_core.domain.lane_occupancy import LaneOccupant
from yoke_core.domain.lint_session_cwd_path_authority import (
    outside_worktree_lanes,
    repo_root_from_worktree_path,
)
from yoke_core.domain.lint_session_cwd_read_only_signatures import (
    GIT_INSPECTION_SUBS,
    GIT_LISTING_SUBS,
    git_subcommand_index,
)

FAILURE_CLASS = "foreign_lane"

# Any of these could chain, redirect, or substitute a second command into
# a call this rule is about to let into somebody else's lane.
_SHELL_METACHARACTERS = (";", "&", "|", ">", "<", "$(", "`")
# ``git diff`` / ``log`` / ``show`` write a file when handed this flag.
_GIT_OUTPUT_FLAG = "--output"


def is_read_only_git_inspection(command: str) -> bool:
    """True when ``command`` is one plain Git call that cannot write."""
    if not command or not command.strip():
        return False
    if any(meta in command for meta in _SHELL_METACHARACTERS):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    index = git_subcommand_index(tokens)
    if index is None:
        return False
    if any(
        token == _GIT_OUTPUT_FLAG or token.startswith(f"{_GIT_OUTPUT_FLAG}=")
        for token in tokens
    ):
        return False
    if tokens[index] in GIT_INSPECTION_SUBS:
        return True
    if tokens[index] not in GIT_LISTING_SUBS:
        return False
    return all(token.startswith("-") for token in tokens[index + 1:])


def governed_targets(
    targets: Sequence[str],
    repo_roots: Sequence[str],
    command: str,
) -> List[str]:
    """Return the targets the session-cwd policy still decides on.

    A read-only Git inspection reads a lane without writing to it or
    disturbing its holder, so its lane targets are outside both the
    ownership question and the authority question.
    """
    if not is_read_only_git_inspection(command):
        return list(targets)
    return outside_worktree_lanes(targets, repo_roots)


def allowed_inspection_lines() -> List[str]:
    """Name the Git calls a held lane still accepts, from the live sets."""
    inspection = "|".join(sorted(GIT_INSPECTION_SUBS))
    listing = "|".join(sorted(GIT_LISTING_SUBS))
    return [
        "Read-only Git inspection of that lane IS allowed — one plain git "
        "call, no redirection, chaining, or --output file:",
        "",
        f"  git -C <lane> ({inspection}) ...",
        f"  git -C <lane> ({listing})"
        "   # listing form only, no positional argument",
        "",
    ]


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
    """Name the lane, its holder, what is still allowed, and the way out."""
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
        lines += [
            "That lane has a live work claim, and this read is not a Git "
            "inspection of it. Read content through the shared object store "
            "from the main checkout:",
            "",
            f"  git -C {main} show <rev>:<path>",
            "",
        ]
    lines += allowed_inspection_lines()
    lines += [
        "Either coordinate with the holding session, or take the "
        "claim yourself once it is free:",
        "",
        f"  yoke claims work acquire --item {acquire_ref} "
        '--reason "<why you are taking over>"',
    ]
    return "\n".join(lines)


__all__ = [
    "FAILURE_CLASS",
    "allowed_inspection_lines",
    "build_denial_message",
    "governed_targets",
    "is_read_only_git_inspection",
]
