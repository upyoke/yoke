"""Resolve shell and native-file operand roles for an executing client."""

from __future__ import annotations
from typing import Any, Mapping
from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell
from yoke_core.domain.lint_command_extract import extract_command
from yoke_core.domain.lint_session_cwd_target_extract import (
    APPLY_PATCH_TOOL_NAMES,
    _is_apply_patch_payload,
    _payload_tool_name,
    _tool_input,
    _resolve_target_paths,
    extract_payload_command,
    resolve_payload_cwd,
    analyze_payload_write_targets,
)
from yoke_core.domain.observe_apply_patch_parser import parse_patch
from yoke_core.domain.lint_session_cwd_home import expand_machine_home

UNRESOLVED_HOME_PATH = "unresolved_executing_machine_home"


def extract_payload_path_uses(
    payload: Mapping[str, Any],
    *,
    machine_home: str | None = None,
    shell: ShellParse | None = None,
):
    """Resolve roles against the executing machine's segment cwds and home."""
    from yoke_core.domain.lint_shell_path_use import (
        PathRole,
        PathUse,
        analyze_shell_path_use,
    )
    from yoke_core.domain.command_workdir import command_segment_cwds

    if not isinstance(payload, Mapping):
        return ()
    command = extract_payload_command(payload)
    parsed = shell if shell is not None else parse_shell(extract_command(payload))
    cwd, segment_cwds = command_segment_cwds(
        payload, machine_home=machine_home, shell=parsed
    )
    tool = _payload_tool_name(payload)
    role = (
        PathRole.WRITE
        if tool in {"Write", "Edit", *APPLY_PATCH_TOOL_NAMES}
        else PathRole.READ
    )
    uses = []
    declared = resolve_payload_cwd(payload)
    if expand_machine_home(declared, machine_home=machine_home).startswith("~"):
        uses.append(PathUse(declared, PathRole.UNKNOWN))
    file_path = _tool_input(payload).get("file_path")
    if isinstance(file_path, str) and file_path.strip():
        uses.append(PathUse(file_path, role))
    if command:
        if _is_apply_patch_payload(payload):
            uses.extend(
                PathUse(path, role) for path in parse_patch(command).all_paths()
            )
        else:
            analysis = analyze_shell_path_use(parsed, segment_cwds=segment_cwds)
            uses.extend(analysis.uses)
            writes = analyze_payload_write_targets(
                payload, shell=parsed, segment_cwds=segment_cwds
            )
            uses.extend(PathUse(path, PathRole.WRITE) for path in writes.targets)
            if not analysis.local_targets and analysis.inspection_only:
                uses.append(PathUse(cwd, PathRole.CAPACITY))
    resolved = []
    for use in uses:
        expanded = expand_machine_home(use.path, machine_home=machine_home)
        if use.role != PathRole.REMOTE and expanded.startswith("~"):
            resolved.append(PathUse(use.path, PathRole.UNKNOWN))
        elif use.role == PathRole.REMOTE:
            resolved.append(use)
        else:
            resolved.extend(
                PathUse(path, use.role)
                for path in _resolve_target_paths(
                    [use.path],
                    cwd,
                    machine_home=machine_home,
                )
            )
    return tuple(dict.fromkeys(resolved))
