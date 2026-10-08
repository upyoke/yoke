"""Resolve the directory a shell command actually runs in.

The call's declared workdir wins — the hook client stamps it onto
``tool_input.workdir`` from the source the harness manifest names under
``identity.command_workdir_source`` — then the payload cwd. Leading ``cd``
statements, joined by ``&&``, ``;``, or a newline, then move it exactly as
the shell will before any later statement runs. Relative and computed
write destinations resolve against this one answer.

A leading ``cd`` whose destination cannot be read (a variable, ``cd -``,
a relative hop with no base) stops the walk at the last directory that
*was* readable, so an unreadable hop never invents a destination.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from yoke_core.domain.lint_command_extract import extract_command
from yoke_core.domain.lint_session_cwd_control_plane import resolve_authority_cwd
from yoke_core.domain.lint_session_cwd_home import expand_machine_home
from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    strip_heredoc_syntax,
)
from yoke_core.domain.lint_shell_target_tokens import shell_command_segments

_CD_OPTIONS = frozenset({"-L", "-P", "-e", "-@"})


def _absolute(raw: str, machine_home: str | None = None) -> str:
    return str(Path(expand_machine_home(raw, machine_home=machine_home)).resolve())


def _cd_destination(segment: list[str]) -> str | None:
    """Return the operand of a plain ``cd DIR`` segment, else ``None``."""
    if not segment or segment[0] != "cd":
        return None
    operands = [tok for tok in segment[1:] if tok not in _CD_OPTIONS]
    if len(operands) != 1:
        return None
    return operands[0]


def command_execution_cwd(
    payload: Mapping[str, Any], *, machine_home: str | None = None
) -> str:
    """Return the absolute directory the payload's command runs in, or ``""``."""
    declared = resolve_authority_cwd(payload)
    expanded_base = expand_machine_home(declared, machine_home=machine_home)
    cwd = (
        _absolute(expanded_base, machine_home)
        if expanded_base and not expanded_base.startswith("~")
        else ""
    )
    command = extract_command(payload)
    if not command:
        return cwd
    for segment in shell_command_segments(strip_heredoc_syntax(command)):
        destination = _cd_destination(segment)
        if destination is None:
            break
        expanded = expand_machine_home(destination, machine_home=machine_home)
        if (
            "$" in expanded
            or "`" in expanded
            or expanded == "-"
            or expanded.startswith("~")
        ):
            break
        if not os.path.isabs(expanded):
            if not cwd:
                break
            expanded = os.path.join(cwd, expanded)
        cwd = _absolute(expanded, machine_home)
    return cwd


__all__ = ["command_execution_cwd"]
