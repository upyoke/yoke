"""Resolve the directory a shell command actually runs in.

The call's declared workdir wins — the hook client stamps it onto
``tool_input.workdir`` from the source the harness manifest names under
``identity.command_workdir_source`` — then the payload cwd. Leading ``cd``
statements, joined by ``&&``, ``;``, or a newline (bare ``NAME=value``
statements between them run nothing), then move it exactly as
the shell will before any later statement runs. Relative and computed
write destinations resolve against this one answer, except where a later
``cd`` moved the segment that names them (:func:`command_segment_cwds`).

A ``cd $NAME`` resolves through assignments written before it (a literal
or an ``mktemp`` path, :func:`segment_variable_bindings`). A leading
``cd`` whose destination still cannot be read (an unbound variable,
``cd -``, a relative hop with no base) stops the walk at the last
directory that *was* readable, so an unreadable hop never invents a
destination.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from yoke_contracts.hook_runner.shell_parse import (
    ShellParse,
    advance_cwd,
    cd_destination,
    parse_shell,
)
from yoke_core.domain.lint_command_extract import extract_command
from yoke_core.domain.lint_session_cwd_control_plane import resolve_authority_cwd
from yoke_core.domain.lint_session_cwd_home import expand_machine_home
from yoke_core.domain.lint_shell_target_tokens import (
    is_assignment_statement,
    segment_variable_bindings,
)


def _absolute(raw: str, machine_home: str | None = None) -> str:
    return str(Path(expand_machine_home(raw, machine_home=machine_home)).resolve())


def _declared_cwd(payload: Mapping[str, Any], machine_home: str | None) -> str:
    declared = resolve_authority_cwd(payload)
    expanded = expand_machine_home(declared, machine_home=machine_home)
    if not expanded or expanded.startswith("~"):
        return ""
    return _absolute(expanded, machine_home)


def _bindings(parsed: ShellParse) -> Sequence[Mapping[str, str]]:
    return segment_variable_bindings([segment.text for segment in parsed.segments])


def _leading_cd_cwd(
    cwd: str,
    parsed: ShellParse,
    machine_home: str | None,
    bindings: Sequence[Mapping[str, str]],
) -> str:
    for index, segment in enumerate(parsed.segments):
        if is_assignment_statement(segment.text):
            continue  # ``S=...`` runs nothing; a later ``cd $S`` still leads.
        destination = cd_destination(segment.argv)
        if destination is None:
            break
        expanded = expand_machine_home(destination, machine_home=machine_home)
        moved = (
            ""
            if expanded.startswith("~")
            else advance_cwd(cwd, expanded, bindings=bindings[index])
        )
        if not moved:
            break
        cwd = moved
    return cwd


def command_execution_cwd(
    payload: Mapping[str, Any], *, machine_home: str | None = None
) -> str:
    """Return the absolute directory the payload's command runs in, or ``""``."""
    cwd = _declared_cwd(payload, machine_home)
    parsed = parse_shell(extract_command(payload))
    return _leading_cd_cwd(cwd, parsed, machine_home, _bindings(parsed))


def command_segment_cwds(
    payload: Mapping[str, Any],
    *,
    machine_home: str | None = None,
    shell: ShellParse | None = None,
) -> tuple[str, list[str]]:
    """Return the execution cwd plus each segment's directory where it differs.

    The list is aligned with ``shell.segments``. An entry is ``""`` where
    the segment runs in the execution cwd or where an unreadable ``cd``
    hides its directory; both resolve against the execution cwd.
    """
    parsed = shell if shell is not None else parse_shell(extract_command(payload))
    declared = _declared_cwd(payload, machine_home)
    bindings = _bindings(parsed)
    cwd = _leading_cd_cwd(declared, parsed, machine_home, bindings)
    segment_cwds = parsed.segment_cwds(declared, home=machine_home, bindings=bindings)
    return cwd, [path if path != cwd else "" for path in segment_cwds]


__all__ = ["command_execution_cwd", "command_segment_cwds"]
