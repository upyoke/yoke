"""Remote-argv recognition for ``yoke qa mission host-command``.

``yoke qa mission host-command ... -- ARGV...`` ships everything after
the ``--`` separator over an awaiting mission execution's retained Test
Machine lease and runs it on that **remote** host. Paths in that argv
name the Test Machine's filesystem, never this machine's, so the
session-cwd write-authority lint must not read them as local write
targets: doing so refused ``-- /bin/ls /Users/testy`` while letting
path-free ``-- /bin/pwd`` through, narrowing the mission instrument to
commands that happen to mention no path at all.

The shell target extractor
(:mod:`lint_session_cwd_target_extract_shell`) consumes
:func:`remote_argv_indexes` to skip those tokens, and the denial
renderer (:mod:`lint_session_cwd_control_plane`) consumes
:func:`host_command_exemption_note` so an invocation that is still
refused for some other reason says why the exemption did not cover the
target it named.
"""

from __future__ import annotations

from typing import List, Sequence

from yoke_core.domain.lint_shell_target_tokens import shell_command_segments


HOST_COMMAND_SUBCOMMAND = ("qa", "mission", "host-command")

# Global ``yoke`` flags whose value must not be mistaken for a subcommand.
YOKE_VALUE_FLAGS = frozenset({"--env", "--config", "--session-id"})

EXEMPTION_NOTE = (
    "\nhost-command remote-argv exemption: this call is `yoke qa mission "
    "host-command`, whose argv after `--` runs on the Test Machine over "
    "the mission's retained lease. Those paths were NOT classified as "
    "local write targets. The target named above came from the part of "
    "the call that does run locally — a redirect, a flag value, or the "
    "call's own working directory. Correct that local target, or run the "
    "command from a path this session's claim covers.\n"
)


def yoke_subcommand_positionals(
    tokens: Sequence[str],
    *,
    limit: int,
) -> List[str]:
    """Return up to ``limit`` subcommand positionals of a ``yoke`` segment.

    Walks past the ``yoke`` head, consuming the value of every global
    flag in :data:`YOKE_VALUE_FLAGS` so ``yoke --env prod qa mission ...``
    reports the same subcommand as the bare form. Stops at a ``--``
    separator: everything beyond it is operand text, not subcommand
    naming.
    """
    positionals: List[str] = []
    seen_command = False
    index = 0
    while index < len(tokens) and len(positionals) < limit:
        token = tokens[index]
        if token == "--":
            break
        if token in YOKE_VALUE_FLAGS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        if not seen_command:
            seen_command = True
            index += 1
            continue
        positionals.append(token)
        index += 1
    return positionals


def is_host_command_segment(command_base: str, tokens: Sequence[str]) -> bool:
    """True when ``tokens`` invoke ``yoke qa mission host-command``."""
    if command_base != "yoke":
        return False
    positionals = yoke_subcommand_positionals(
        tokens,
        limit=len(HOST_COMMAND_SUBCOMMAND),
    )
    return tuple(positionals) == HOST_COMMAND_SUBCOMMAND


def remote_argv_indexes(command_base: str, tokens: Sequence[str]) -> set[int]:
    """Return the token indexes that run on the remote Test Machine.

    Empty for every segment that is not a host-command invocation, and
    for a host-command invocation written without the ``--`` separator
    (which the CLI itself rejects). Otherwise every index after the
    separator, because the whole argv is shipped over the lease.

    Shell redirect syntax trailing that argv is not part of it — the
    shell performs a redirect on this machine — so the extractor
    resolves redirects before consulting this index set.
    """
    if not is_host_command_segment(command_base, tokens):
        return set()
    try:
        separator = list(tokens).index("--")
    except ValueError:
        return set()
    return set(range(separator + 1, len(tokens)))


def is_host_command(command: str) -> bool:
    """True when any invocation in ``command`` is a host-command call."""
    for segment in shell_command_segments(command):
        base = next(
            (tok.rsplit("/", 1)[-1] for tok in segment if not tok.startswith("-")),
            "",
        )
        if is_host_command_segment(base, segment):
            return True
    return False


def host_command_exemption_note(command: str) -> str:
    """Return the denial clause for a refused host-command call, else ``""``."""
    if not command or not is_host_command(command):
        return ""
    return EXEMPTION_NOTE


__all__ = [
    "EXEMPTION_NOTE",
    "HOST_COMMAND_SUBCOMMAND",
    "YOKE_VALUE_FLAGS",
    "host_command_exemption_note",
    "is_host_command",
    "is_host_command_segment",
    "remote_argv_indexes",
    "yoke_subcommand_positionals",
]
