"""Extract target paths from PreToolUse payloads for claim-based validation.

The session-cwd lint validates per-call targets against claim authority.
This module extracts the paths a tool call would touch; the validator in
:mod:`lint_session_cwd_validate` decides claimed worktree vs control plane
vs free path. Write-only consumers use
:func:`extract_payload_write_targets` so fixture strings and read operands
are not write targets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, List, Mapping, Sequence, Tuple

from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell
from yoke_contracts.hook_runner.shell_parse import strip_env_prefix
from yoke_core.domain.lint_command_extract import extract_command
from yoke_core.domain.lint_python_write_target_extract import (
    analyze_python_heredoc_writes,
)
from yoke_core.domain.lint_shell_target_tokens import (
    resolve_path_operands,
    shell_variable_bindings,
)
from yoke_core.domain.lint_session_cwd_home import expand_machine_home
from yoke_core.domain.lint_session_cwd_read_only_signatures import git_write_targets
from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    FLAG_BINARY,
    FLAG_EQUALS_PREFIXES,
    REDIRECT_OPERATORS,
    extract_command_targets,
    in_segment_cwd,
    is_file_redirect_operand,
    without_heredoc_operators,
)
from yoke_core.domain.observe_apply_patch_parser import parse_patch


APPLY_PATCH_TOOL_NAMES = frozenset({"apply_patch", "ApplyPatch"})
_ALL_POSITIONAL_WRITE_COMMANDS = frozenset(
    {
        "touch",
        "rm",
        "rmdir",
        "unlink",
        "mkdir",
        "tee",
        "truncate",
        "sponge",
    }
)
_LAST_POSITIONAL_WRITE_COMMANDS = frozenset({"cp", "mv", "install"})
SHELL_WRITE_COMMAND_BASES = (
    _ALL_POSITIONAL_WRITE_COMMANDS | _LAST_POSITIONAL_WRITE_COMMANDS | {"patch"}
)
_GLUED_REDIRECT_RE = re.compile(r"^(?:[012]?>>?|&>>?)(.+)$")
_APP_CONTAINER_ROOT = Path("/app")


def glued_file_redirect_target(token: str) -> str | None:
    """Return the file operand of a glued redirect, or ``None``.

    Fd duplications such as ``2>&1`` / ``>&2`` are not filesystem writes.
    """
    match = _GLUED_REDIRECT_RE.match(token)
    if match is None:
        return None
    target = match.group(1).rstrip(";&")
    return target if is_file_redirect_operand(target) else None


def _tool_input(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = (
        payload.get("tool_input")
        or payload.get("toolInput")
        or payload.get("input")
        or {}
    )
    return value if isinstance(value, Mapping) else {}


def _payload_tool_name(payload: Mapping[str, Any]) -> str:
    for key in ("tool_name", "toolName", "tool", "event_name"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _is_apply_patch_payload(payload: Mapping[str, Any]) -> bool:
    return _payload_tool_name(payload) in APPLY_PATCH_TOOL_NAMES


def resolve_payload_cwd(
    payload: Mapping[str, Any],
    *,
    fallback: str = "",
) -> str:
    """Return the call's declared cwd, excluding a bare app container root."""
    if not isinstance(payload, Mapping):
        return fallback
    tool_input = _tool_input(payload)
    for source in (tool_input, payload):
        for key in ("workdir", "working_directory"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value

    project_candidates = [payload.get("project_dir"), payload.get("workspace")]
    roots = payload.get("workspace_roots")
    if isinstance(roots, list):
        project_candidates.extend(roots)
    project_cwd = next(
        (
            value
            for value in project_candidates
            if isinstance(value, str)
            and value.strip()
            and Path(value).expanduser() != _APP_CONTAINER_ROOT
        ),
        "",
    )
    raw_cwd = payload.get("cwd")
    if isinstance(raw_cwd, str) and raw_cwd.strip():
        return (
            project_cwd
            if Path(raw_cwd).expanduser() == _APP_CONTAINER_ROOT
            else raw_cwd
        )
    return project_cwd or fallback


def _resolve_target_paths(
    paths: List[str],
    cwd: str,
    *,
    machine_home: str | None = None,
) -> List[str]:
    out: List[str] = []
    for raw in paths:
        path = Path(expand_machine_home(raw.strip(), machine_home=machine_home))
        if path.is_absolute():
            out.append(str(path))
        elif cwd:
            base = expand_machine_home(cwd, machine_home=machine_home)
            out.append(str((Path(base) / path).resolve()))
    return out


def _dedupe_paths(paths: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for raw in paths:
        key = raw.strip()
        if key and key not in seen:
            seen.add(key)
            out.append(raw)
    return out


def extract_payload_targets(
    payload: Mapping[str, Any],
    *,
    machine_home: str | None = None,
) -> List[str]:
    """Project local paths from the shared operand roles."""
    from yoke_core.domain.lint_shell_path_use import PathRole
    from yoke_core.domain.lint_payload_path_use import extract_payload_path_uses

    return _dedupe_paths(
        [
            use.path
            for use in extract_payload_path_uses(payload, machine_home=machine_home)
            if use.role != PathRole.REMOTE
        ]
    )


@dataclass(frozen=True)
class PayloadWriteTargets:
    """Resolved write positions and uncertainty requiring restrictive handling."""

    targets: List[str]
    unresolved_variable: bool
    unresolved_writes: Tuple[str, ...] = ()


def analyze_payload_write_targets(
    payload: Mapping[str, Any],
    *,
    protected_roots: Tuple[str, ...] = (),
    shell: ShellParse | None = None,
    segment_cwds: Sequence[str] = (),
) -> PayloadWriteTargets:
    """Return write-position paths; ``segment_cwds`` moves relative ones."""
    if not isinstance(payload, Mapping):
        return PayloadWriteTargets([], False)
    tool_input = _tool_input(payload)
    out: List[str] = []

    file_path = tool_input.get("file_path")
    if isinstance(file_path, str) and file_path.strip():
        out.append(file_path)

    command = extract_payload_command(payload)
    if not command:
        return PayloadWriteTargets(_dedupe_paths(out), False)
    if _is_apply_patch_payload(payload):
        out.extend(parse_patch(command).all_paths())
        return PayloadWriteTargets(_dedupe_paths(out), False)

    parsed = shell if shell is not None else parse_shell(command)
    shell_targets, unresolved = _extract_shell_write_targets(parsed, segment_cwds)
    out.extend(shell_targets)
    python_writes = analyze_python_heredoc_writes(
        parsed, protected_roots=protected_roots, segment_cwds=segment_cwds
    )
    out.extend(python_writes.targets)
    return PayloadWriteTargets(
        _dedupe_paths(out),
        unresolved
        or (python_writes.free_writes and not python_writes.unresolved_writes),
        python_writes.unresolved_writes,
    )


def extract_payload_write_targets(payload: Mapping[str, Any]) -> List[str]:
    """Return only paths occupying real write positions in a tool payload."""
    return analyze_payload_write_targets(payload).targets


def payload_has_embedded_python_write(
    payload: Mapping[str, Any], shell: ShellParse | None = None
) -> bool:
    """True when a Bash payload executes an embedded Python write call."""
    if not isinstance(payload, Mapping) or _is_apply_patch_payload(payload):
        return False
    command = extract_payload_command(payload)
    return bool(command) and analyze_python_heredoc_writes(shell or command).detected


def _extract_shell_write_targets(
    parsed: ShellParse, segment_cwds: Sequence[str]
) -> Tuple[List[str], bool]:
    from yoke_core.domain.lint_shell_path_use import analyze_shell_path_use

    result = analyze_shell_path_use(parsed, segment_cwds=segment_cwds)
    return list(result.write_targets), result.unresolved_writes


def resolve_shell_write_operands(
    command: str | ShellParse,
    *,
    bindings=None,
    segment_cwds: Sequence[str] = (),
) -> Tuple[List[str], bool]:
    """Resolve existing write positions using bindings from the whole body."""
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    if bindings is None:
        bindings = shell_variable_bindings(parsed.command)
    out: List[str] = []
    unresolved = False
    for index, segment in enumerate(parsed.segments):
        # Redirects are read before the reserved words are dropped: a
        # word-list header carries no operands but can still redirect.
        words = without_heredoc_operators(segment.tokens)
        clean, redirects = _split_redirect_targets(words)
        clean = strip_env_prefix(clean)
        resolved, segment_unresolved = resolve_path_operands(redirects, bindings)
        out.extend(in_segment_cwd(resolved, segment_cwds, index))
        unresolved = unresolved or segment_unresolved
        if not clean:
            continue
        command_base = PurePath(clean[0]).name
        if command_base == "git":
            git_targets, git_unresolved = git_write_targets(segment, bindings=bindings)
            out.extend(in_segment_cwd(git_targets, segment_cwds, index))
            unresolved = unresolved or git_unresolved
            continue
        args = clean[1:]
        positionals = [arg for arg in args if arg != "-" and not arg.startswith("-")]
        if command_base in _LAST_POSITIONAL_WRITE_COMMANDS and positionals:
            positionals = positionals[-1:]
        elif command_base not in _ALL_POSITIONAL_WRITE_COMMANDS:
            continue
        resolved, segment_unresolved = resolve_path_operands(positionals, bindings)
        out.extend(in_segment_cwd(resolved, segment_cwds, index))
        unresolved = unresolved or segment_unresolved
    return _dedupe_paths(out), unresolved


def _split_redirect_targets(tokens: List[str]) -> Tuple[List[str], List[str]]:
    clean: List[str] = []
    targets: List[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in REDIRECT_OPERATORS:
            if i + 1 < len(tokens) and is_file_redirect_operand(tokens[i + 1]):
                targets += [tokens[i + 1]]
            i += 2
            continue
        glued = glued_file_redirect_target(token)
        if glued is not None:
            targets += [glued]
            i += 1
            continue
        clean += [token]
        i += 1
    return clean, targets


def extract_payload_command(payload: Mapping[str, Any]) -> str:
    """Return the Bash command, or apply_patch text, from a PreToolUse payload."""
    if not isinstance(payload, Mapping):
        return ""
    command = extract_command(payload)
    if command:
        return command
    if _is_apply_patch_payload(payload):
        tool_input = _tool_input(payload)
        for key in ("input", "patch", "diff"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


__all__ = [
    "FLAG_BINARY",
    "FLAG_EQUALS_PREFIXES",
    "SHELL_WRITE_COMMAND_BASES",
    "PayloadWriteTargets",
    "analyze_payload_write_targets",
    "extract_command_targets",
    "extract_payload_command",
    "extract_payload_targets",
    "extract_payload_write_targets",
    "glued_file_redirect_target",
    "payload_has_embedded_python_write",
    "resolve_payload_cwd",
]
