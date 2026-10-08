"""Resolve shell and native-file operand roles for an executing client."""

from __future__ import annotations
from typing import Any, Mapping
from yoke_core.domain.lint_session_cwd_target_extract import (
    APPLY_PATCH_TOOL_NAMES,
    _is_apply_patch_payload,
    _payload_tool_name,
    _tool_input,
    _resolve_target_paths,
    extract_payload_command,
    analyze_payload_write_targets,
)
from yoke_core.domain.observe_apply_patch_parser import parse_patch


def extract_payload_path_uses(
    payload: Mapping[str, Any], *, machine_home: str | None = None
):
    """Resolve roles against the executing machine's declared cwd and home."""
    from yoke_core.domain.lint_shell_path_use import (
        PathRole,
        PathUse,
        analyze_shell_path_use,
    )
    from yoke_core.domain.command_workdir import command_execution_cwd

    if not isinstance(payload, Mapping):
        return ()
    cwd = command_execution_cwd(payload, machine_home=machine_home)
    command = extract_payload_command(payload)
    tool = _payload_tool_name(payload)
    role = (
        PathRole.WRITE
        if tool in {"Write", "Edit", *APPLY_PATCH_TOOL_NAMES}
        else PathRole.READ
    )
    uses = []
    file_path = _tool_input(payload).get("file_path")
    if isinstance(file_path, str) and file_path.strip():
        uses.append(PathUse(file_path, role))
    if command:
        if _is_apply_patch_payload(payload):
            uses.extend(
                PathUse(path, role) for path in parse_patch(command).all_paths()
            )
        else:
            analysis = analyze_shell_path_use(command)
            uses.extend(analysis.uses)
            uses.extend(
                PathUse(path, PathRole.WRITE)
                for path in analyze_payload_write_targets(payload).targets
            )
            if not analysis.local_targets and analysis.inspection_only:
                uses.append(PathUse(cwd, PathRole.CAPACITY))
    resolved = []
    for use in uses:
        if use.role == PathRole.REMOTE:
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
