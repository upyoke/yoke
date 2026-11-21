"""How the lane-main-write guard arrived at the path it refused.

A refusal an operator cannot reproduce mentally is a refusal they
resolve by trial and error. The guard therefore carries, alongside the
path it decided on, the derivation that produced it: which token was
read, where that token came from, and how it resolved to a path inside
the main checkout.

The derivation determines what the refusal teaches:

* ``tool_target`` — the path came from an Edit/Write/patch call's own
  file-path field. It is already the literal destination.
* ``command_token`` — the path was read out of a command body's write
  position. A relative token resolves against the call's working
  directory, so the same command run from the lane would land in the
  lane.
* ``working_directory`` — a write shape affected its effective directory.
* ``unreadable_destination`` — the write destination is computed at runtime.
* ``git_state_change`` — Git changes repository state in its effective
  directory.

Nothing here assumes a repository layout, checkout name, or item
prefix — every path in the rendered block is a value the caller
derived from the live claim or the call itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import shlex
from yoke_contracts.hook_runner.bash_paths import shell_path_spellings
from typing import Sequence, Tuple

from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree

TOOL_TARGET = "tool_target"
COMMAND_TOKEN = "command_token"
WORKING_DIRECTORY = "working_directory"
UNREADABLE_DESTINATION = "unreadable_destination"
GIT_STATE_CHANGE = "git_state_change"

# The free temp file the computed-message recovery writes through. It is
# on the free-path allowlist from any lane, which is what makes the
# recipe runnable by the session the refusal is teaching.
RECOVERY_MESSAGE_FILE = "/tmp/message.txt"

LANE_EDIT_GUIDANCE = (
    "While this session holds an implementation-lane work claim, tracked "
    "source edits belong in the lane worktree — not the main checkout. "
    "Copy the in-lane path above into your Edit/Write/Bash call; a relative "
    "path resolves against the call's workdir, then each `cd` that runs "
    "before it, so running the call in the lane also lands it there."
)

_SOURCE_NOTES = {
    TOOL_TARGET: "file path of the tool call",
    COMMAND_TOKEN: "write target read from the command body",
}
_LABEL_WIDTH = 15


@dataclass(frozen=True)
class TargetDerivation:
    """Why the guard resolved a call to one path in the main checkout."""

    source: str
    token: str = ""
    working_directory: str = ""
    main_checkout: str = ""
    unresolved_writes: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def fell_back_to_cwd(self) -> bool:
        """True when no write destination could be read from the call."""
        return self.source in {WORKING_DIRECTORY, UNREADABLE_DESTINATION}


@dataclass(frozen=True)
class MainWriteHit:
    """One refusable path plus the lane claim and derivation behind it."""

    path: str
    claim: ClaimedWorktree
    derivation: TargetDerivation


@dataclass(frozen=True)
class DerivationContext:
    """Call-wide facts every target collected from one payload shares."""

    working_directory: str
    source: str
    unresolved_writes: Tuple[str, ...]
    git_subcommand: str


def derivation_context(
    working_directory: str,
    is_tool_target: bool,
    fell_back_to_cwd: bool,
    unresolved_writes: Sequence[str],
    *,
    unreadable: bool,
    git_subcommand: str,
) -> DerivationContext:
    """Resolve the derivation facts for a target."""
    if git_subcommand:
        source = GIT_STATE_CHANGE
    elif fell_back_to_cwd:
        source = UNREADABLE_DESTINATION if unreadable else WORKING_DIRECTORY
    else:
        source = TOOL_TARGET if is_tool_target else COMMAND_TOKEN
    return DerivationContext(
        working_directory=working_directory,
        source=source,
        unresolved_writes=tuple(unresolved_writes),
        git_subcommand=git_subcommand,
    )


def build_hit(
    path: str,
    claim: ClaimedWorktree,
    token: str,
    main_checkout: str,
    context: DerivationContext,
) -> MainWriteHit:
    """Pair a refusable path with the derivation that produced it."""
    return MainWriteHit(
        path=path,
        claim=claim,
        derivation=TargetDerivation(
            source=context.source,
            token=(
                f"git {context.git_subcommand}" if context.git_subcommand
                else token if context.source in {TOOL_TARGET, COMMAND_TOKEN} else ""
            ),
            working_directory=context.working_directory,
            main_checkout=main_checkout,
            unresolved_writes=context.unresolved_writes,
        ),
    )


def _line(label: str, value: str) -> str:
    return f"{(label + ':').ljust(_LABEL_WIDTH)}{value}"


def _resolution_line(derivation: TargetDerivation, attempted_path: str) -> str:
    if derivation.source == GIT_STATE_CHANGE:
        return _line("Resolved", f"Git runs in {derivation.working_directory}")
    if derivation.source == WORKING_DIRECTORY:
        return _line("Resolved", f"the command writes in {derivation.working_directory}")
    if derivation.fell_back_to_cwd:
        return _line(
            "Resolved",
            f"no write target found — fell back to the working directory "
            f"{derivation.working_directory or '(unknown)'}",
        )
    if derivation.token == attempted_path:
        return _line("Resolved", "token is already an absolute path")
    if derivation.working_directory:
        return _line(
            "Resolved",
            f"relative to the working directory "
            f"{derivation.working_directory} -> {attempted_path}",
        )
    return _line("Resolved", attempted_path)


def format_derivation(
    derivation: TargetDerivation,
    *,
    attempted_path: str,
) -> str:
    """Render the extracted-token / resolution block for a refusal."""
    lines = []
    if derivation.source == UNREADABLE_DESTINATION:
        lines.append(
            _line(
                "Extracted", "(nothing — this call names no readable write destination)"
            )
        )
    elif derivation.token:
        note = _SOURCE_NOTES.get(derivation.source, "")
        suffix = f"   ({note})" if note else ""
        lines.append(_line("Extracted", f"{derivation.token}{suffix}"))
    lines.append(_resolution_line(derivation, attempted_path))
    for expression in derivation.unresolved_writes:
        lines.append(_line("Unresolved", expression))
    if derivation.main_checkout:
        lines.append(
            _line(
                "Main checkout",
                f"{derivation.main_checkout} — the resolved path is inside it",
            )
        )
    return "\n".join(lines)


def format_derivation_guidance(
    derivation: TargetDerivation,
    *,
    lane_path: str = "",
) -> str:
    """Explain how to run the refused command in the held lane."""
    if derivation.fell_back_to_cwd or derivation.source == GIT_STATE_CHANGE:
        lane = lane_path or "<lane path>"
        shell_lane = shlex.quote(shell_path_spellings(lane)[0]) if lane_path else lane
        recovery = (
            "Run the call in the lane: declare "
            f"{lane} as the call's workdir, or make `cd {shell_lane}` the "
            "command's first statement (followed by `&&`, `;`, or a newline)."
        )
        message_file = (
            "For a commit whose message is computed, write the message to a "
            f"free temp file and run `git -C {shell_lane} commit -F "
            f"{RECOVERY_MESSAGE_FILE}`."
        )
        if derivation.source == GIT_STATE_CHANGE:
            recovery += f" If the command already uses `git -C`, point it at {lane}."
            if derivation.token == "git commit":
                return f"{recovery} {message_file}"
            return recovery
        if derivation.source == UNREADABLE_DESTINATION:
            return (
                "The guard could not resolve the unreadable destination, so it used "
                f"the working directory above. {recovery} {message_file} "
                "For file writes, spell each destination as a literal absolute lane path."
            )
        return recovery
    return LANE_EDIT_GUIDANCE


def first_hit_fields(
    hits: Sequence[MainWriteHit],
) -> Tuple[str, ClaimedWorktree, TargetDerivation]:
    """Unpack the refused hit the guard reports on."""
    hit = hits[0]
    return hit.path, hit.claim, hit.derivation


__all__ = [
    "COMMAND_TOKEN",
    "DerivationContext",
    "GIT_STATE_CHANGE",
    "LANE_EDIT_GUIDANCE",
    "MainWriteHit",
    "RECOVERY_MESSAGE_FILE",
    "TOOL_TARGET",
    "TargetDerivation",
    "UNREADABLE_DESTINATION",
    "WORKING_DIRECTORY",
    "build_hit",
    "derivation_context",
    "first_hit_fields",
    "format_derivation",
    "format_derivation_guidance",
]
