"""The foreign-lane rule: what a held lane accepts, and how it refuses.

Kept beside the policy rather than inside it because this refusal has a
different remedy from every other session-cwd denial. A scope mismatch
tells one session it is outside its own authority, and the fix is that
session's alone. This one says two agents are in the same lane, so the
message has to name the other party and hand back an action that
involves them.

Reads of a held lane are allowed, including a plain ``cat`` or Read and
read-only Git inspection. A worker told to survey the neighbour it
shares a file with needs ``git status`` and ``git diff`` against the
neighbour's tree. Writes and state moves stay refused: the write-target
resolver decides filesystem writes, and a Git call that is not read-only
inspection, a delete, or an in-place ``sed`` moves the lane even when
that resolver has no path to name. Chains and pipelines are allowed only
when every segment is a known read or directory change. Redirects,
substitutions and ``--output`` files retain ordinary authority checks.

The refusal deliberately does NOT suggest stashing or committing. That
advice is addressed to a single author who has dirtied their own tree;
told to a session that has wandered into somebody else's lane it would
convert a refused write into a commit on top of another agent's
uncommitted work.
"""

from __future__ import annotations

from typing import List, Sequence

from yoke_contracts.hook_runner.shell_parse import ShellParse, ShellSegment, parse_shell
from yoke_core.domain.lane_occupancy import LaneOccupant
from yoke_core.domain.lint_session_cwd_path_authority import (
    outside_worktree_lanes,
)
from yoke_core.domain.lint_session_cwd_read_only_signatures import (
    GIT_INSPECTION_SUBS,
    GIT_LISTING_SUBS,
    git_subcommand_index,
)
from yoke_core.domain.project_identity_item_ref import item_ref_for_id

FAILURE_CLASS = "foreign_lane"

# Any of these could chain, redirect, or substitute a second command into
# a call this rule is about to let into somebody else's lane.
_SHELL_METACHARACTERS = (";", "&", "|", ">", "<", "$(", "`")
# ``git diff`` / ``log`` / ``show`` write a file when handed this flag.
_GIT_OUTPUT_FLAG = "--output"


def is_read_only_git_inspection(command: str | ShellSegment) -> bool:
    """True when ``command`` is one plain Git call that cannot write.

    Metacharacters refuse even inside quotes, and any environment prefix
    refuses too: ``GIT_EXTERNAL_DIFF=...`` or ``GIT_PAGER=...`` would run
    another program from inside a read.
    """
    segment = command if isinstance(command, ShellSegment) else None
    text = segment.text if segment is not None else str(command or "")
    if not text.strip() or any(meta in text for meta in _SHELL_METACHARACTERS):
        return False
    if segment is None:
        parsed = parse_shell(text)
        if parsed.unparsed or len(parsed.segments) != 1:
            return False
        segment = parsed.segments[0]
    tokens = list(segment.tokens)
    if segment.argv != segment.tokens:
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
    return all(token.startswith("-") for token in tokens[index + 1 :])


def governed_targets(
    targets: Sequence[str],
    repo_roots: Sequence[str],
    command: str | ShellParse,
) -> List[str]:
    """Return the targets the session-cwd policy still decides on.

    A read-only Git inspection reads a lane without writing to it or
    disturbing its holder, so its lane targets are outside both the
    ownership question and the authority question.
    """
    from yoke_core.domain.lint_session_cwd_read_only_signatures import _match_simple

    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    # The splitter does not descend into substitutions, including quoted ones.
    if any(mark in parsed.command for mark in (">", "<", "$(", "`")):
        return list(targets)
    if parsed.unparsed or not parsed.segments:
        return list(targets)
    for segment in parsed.segments:
        if is_read_only_git_inspection(segment):
            continue
        tokens = segment.tokens
        if len(tokens) == 2 and tokens[0] == "cd" and not tokens[1].startswith("-"):
            continue
        label = _match_simple(segment)
        if not label or label in {"find", "yoke-adapter"}:
            return list(targets)
    return outside_worktree_lanes(targets, repo_roots)


def allowed_inspection_lines() -> List[str]:
    """Name the Git calls a held lane still accepts, from the live sets."""
    inspection = "|".join(sorted(GIT_INSPECTION_SUBS))
    listing = "|".join(sorted(GIT_LISTING_SUBS))
    return [
        "Read-only Git inspection of that lane IS allowed, including chains "
        "of reads and cd; no redirection, substitution, or --output file:",
        "",
        f"  git -C <lane> ({inspection}) ...",
        f"  git -C <lane> ({listing})   # listing form only, no positional argument",
        "",
    ]


def is_lane_mutation(tool_name: str, command: str) -> bool:
    """True when the call writes or moves state in a lane.

    Filesystem writes come from the shared write-target resolver
    (``is_write_operation``). Git that is not read-only inspection, a
    delete, and in-place ``sed`` move the lane without a write path that
    resolver can name.
    """
    from yoke_core.domain.lint_lane_main_write_classify import (
        is_write_operation,
    )
    from yoke_core.domain.lint_shell_path_use import analyze_shell_path_use

    payload = {"tool_name": tool_name, "tool_input": {"command": command}}
    return (
        is_write_operation(tool_name, payload)
        or analyze_shell_path_use(command).mutation
    )


def build_denial_message(
    *,
    offending_target: str,
    occupant: LaneOccupant,
) -> str:
    """Name the lane, its holder, what is still allowed, and the way out."""
    owner = occupant.public_ref or item_ref_for_id(occupant.item_id)
    acquire_ref = occupant.public_ref or "PREFIX-N"
    lines = [
        "Refusing a write into a worktree lane held by another session.",
        "",
        f"  target:  {offending_target}",
        f"  lane:    {occupant.lane_path}",
        f"  owner:   {owner}",
        f"  held by: session {occupant.session_id}",
        "",
    ]
    lines += [
        "That lane has a live work claim. Two agents editing one "
        "worktree share its git index, so staged changes from either "
        "land in whichever one commits first.",
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
    "is_lane_mutation",
    "is_read_only_git_inspection",
]
