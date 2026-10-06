"""Where each harness declares the directory one shell command runs in.

Guards that resolve a relative or computed write destination need the
directory the command *executes* in, not the session's launch cwd. Each
harness carries that fact differently, so this module is its single source.
The renderer copies each entry into ``runtime/harness/<harness_id>/manifest.json``
as ``identity.command_workdir_source`` (see ``runtime/harness/manifest-schema.md``),
and the hook client reads it to stamp ``tool_input.workdir`` before any
evaluation — local or relayed — so the server never needs a client file.

- ``payload_cwd``: the hook payload ``cwd`` already is the shell's directory.
- ``payload_working_directory``: the payload carries
  ``working_directory`` beside the command.
- ``rollout_exec_command_workdir``: hook stdin omits the per-call workdir;
  the session rollout at ``transcript_path`` records it on the matching
  ``exec_command`` call, which only the client machine can read.
"""

from __future__ import annotations

from typing import Literal

CommandWorkdirSource = Literal[
    "payload_cwd",
    "payload_working_directory",
    "rollout_exec_command_workdir",
]

ROLLOUT_EXEC_COMMAND_WORKDIR: CommandWorkdirSource = "rollout_exec_command_workdir"

HARNESS_COMMAND_WORKDIR_SOURCES: dict[str, CommandWorkdirSource] = {
    "claude-code": "payload_cwd",
    "codex": ROLLOUT_EXEC_COMMAND_WORKDIR,
    "cursor": "payload_working_directory",
}


def command_workdir_source(harness_id: str) -> CommandWorkdirSource:
    """Return the declared source; an unknown harness is a named refusal."""
    try:
        return HARNESS_COMMAND_WORKDIR_SOURCES[harness_id]
    except KeyError:
        raise KeyError(
            f"no command_workdir_source declared for harness {harness_id!r}; "
            "add it to yoke_contracts.harness_command_workdir and re-render "
            "the harness manifests"
        ) from None


__all__ = [
    "CommandWorkdirSource",
    "HARNESS_COMMAND_WORKDIR_SOURCES",
    "ROLLOUT_EXEC_COMMAND_WORKDIR",
    "command_workdir_source",
]
