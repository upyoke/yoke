"""How the lane-main-write guard arrived at the path it refused.

A refusal an operator cannot reproduce mentally is a refusal they
resolve by trial and error. The guard therefore carries, alongside the
path it decided on, the derivation that produced it: which token was
read, where that token came from, and how it resolved to a path inside
the main checkout.

Three derivations exist, and the operator's next move differs for each:

* ``tool_target`` — the path came from an Edit/Write/patch call's own
  file-path field. It is already the literal destination.
* ``command_token`` — the path was read out of a command body's write
  position. A relative token resolves against the call's working
  directory, so the same command run from the lane would land in the
  lane.
* ``working_directory`` — nothing readable was found. The command is a
  write shape, but its destination is computed at runtime, so the guard
  fell back to the working directory. Naming that fallback matters:
  the guard is not claiming the command mentioned this path.

Nothing here assumes a repository layout, checkout name, or item
prefix — every path in the rendered block is a value the caller
derived from the live claim or the call itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence, Tuple

from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree

TOOL_TARGET = "tool_target"
COMMAND_TOKEN = "command_token"
WORKING_DIRECTORY = "working_directory"

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
        return self.source == WORKING_DIRECTORY


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


def derivation_source(*, is_tool_target: bool, fell_back_to_cwd: bool) -> str:
    """Name the derivation a collected target came from."""
    if fell_back_to_cwd:
        return WORKING_DIRECTORY
    return TOOL_TARGET if is_tool_target else COMMAND_TOKEN


def derivation_context(
    working_directory: str,
    is_tool_target: bool,
    fell_back_to_cwd: bool,
    unresolved_writes: Sequence[str],
) -> DerivationContext:
    """Resolve the derivation facts shared by one payload's targets."""
    return DerivationContext(
        working_directory=working_directory,
        source=derivation_source(
            is_tool_target=is_tool_target, fell_back_to_cwd=fell_back_to_cwd,
        ),
        unresolved_writes=tuple(unresolved_writes),
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
            token="" if context.source == WORKING_DIRECTORY else token,
            working_directory=context.working_directory,
            main_checkout=main_checkout,
            unresolved_writes=context.unresolved_writes,
        ),
    )


def _line(label: str, value: str) -> str:
    return f"{(label + ':').ljust(_LABEL_WIDTH)}{value}"


def _resolution_line(derivation: TargetDerivation, attempted_path: str) -> str:
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
    derivation: TargetDerivation, *, attempted_path: str,
) -> str:
    """Render the extracted-token / resolution block for a refusal."""
    lines = []
    if derivation.fell_back_to_cwd:
        lines.append(
            _line("Extracted", "(nothing — this call names no readable "
                  "write destination)")
        )
    else:
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


def format_derivation_guidance(derivation: TargetDerivation) -> str:
    """Render the next move, which differs by how the path was derived."""
    if derivation.fell_back_to_cwd:
        return (
            "This command writes through a destination the guard cannot read "
            "— a variable, a loop operand, or a computed path — so it fell "
            "back to the working directory above. A path the command only "
            "mentions as string data is never treated as a write target, and "
            "an unreadable destination is refused rather than guessed. If the "
            "write already lands in the lane, spell each destination as a "
            "literal absolute lane path, or run the command with the lane as "
            "its working directory."
        )
    return (
        "While this session holds an implementation-lane work claim, tracked "
        "source edits belong in the lane worktree — not the main checkout. "
        "Copy the in-lane path above into your Edit/Write/Bash call."
    )


def first_hit_fields(
    hits: Sequence[MainWriteHit],
) -> Tuple[str, ClaimedWorktree, TargetDerivation]:
    """Unpack the refused hit the guard reports on."""
    hit = hits[0]
    return hit.path, hit.claim, hit.derivation


__all__ = [
    "COMMAND_TOKEN",
    "DerivationContext",
    "MainWriteHit",
    "TOOL_TARGET",
    "TargetDerivation",
    "WORKING_DIRECTORY",
    "build_hit",
    "derivation_context",
    "derivation_source",
    "first_hit_fields",
    "format_derivation",
    "format_derivation_guidance",
]
