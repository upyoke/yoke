"""Extract target paths from PreToolUse payloads for claim-based validation.

The session-cwd lint validates per-tool-call **targets** against the
session's claim authority. This module is the target-extraction layer:
given a PreToolUse payload, return the list of paths the tool call
would touch. The validator in :mod:`lint_session_cwd_validate` then
decides whether each target lands under a claimed worktree, the
control plane, or a free path.

Extracted shapes:

* **Edit / Read / Write:** ``tool_input.file_path`` is the canonical
  target.
* **apply_patch:** parse only patch directive paths, never diff content.
* **Bash:** parse the command body and surface any of:
    - ``-C <path>`` (git, make, etc.)
    - ``--rootdir <path>`` / ``--rootdir=<path>`` (pytest)
    - ``--target-root <path>`` / ``--target-root=<path>``
    - ``--worktree-path <path>`` / ``--worktree-path=<path>``
    - ``-w <path>`` (custom Yoke flag)
    - absolute-path positional arguments
* **Relative targets:** resolve against the call's declared workdir.
* **No extractable target:** the caller falls back to the effective project cwd.

Write-only consumers use :func:`extract_payload_write_targets`, which
narrows bodies to paths occupying real write positions. Fixture strings
and read operands are not write targets.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, List, Mapping, Tuple

from yoke_core.domain.lint_python_write_target_extract import (
    analyze_python_heredoc_writes,
)
from yoke_core.domain.lint_shell_target_tokens import (
    resolve_write_operands,
    shell_variable_bindings,
)
from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    FLAG_BINARY,
    FLAG_EQUALS_PREFIXES,
    REDIRECT_OPERATORS,
    extract_command_targets,
    strip_env_prefixes,
    strip_heredoc_syntax,
)
from yoke_core.domain.observe_apply_patch_parser import parse_patch
from yoke_core.domain.path_claim_bash_splitter import split_pipeline


APPLY_PATCH_TOOL_NAMES = frozenset({"apply_patch", "ApplyPatch"})
_ALL_POSITIONAL_WRITE_COMMANDS = frozenset({
    "touch", "mkdir", "tee", "truncate", "sponge",
})
_LAST_POSITIONAL_WRITE_COMMANDS = frozenset({"cp", "mv", "install"})
SHELL_WRITE_COMMAND_BASES = (
    _ALL_POSITIONAL_WRITE_COMMANDS | _LAST_POSITIONAL_WRITE_COMMANDS | {"patch"}
)
_GLUED_REDIRECT_RE = re.compile(r"^(?:[012]?>>?|&>>?)(.+)$")
_FD_DUP_REDIRECT_TARGET_RE = re.compile(r"^&\d+$")
_APP_CONTAINER_ROOT = Path("/app")


def glued_file_redirect_target(token: str) -> str | None:
    """Return the file operand of a glued redirect, or ``None``.

    Fd duplications such as ``2>&1`` / ``>&2`` are not filesystem writes.
    """
    match = _GLUED_REDIRECT_RE.match(token)
    if match is None:
        return None
    target = match.group(1)
    if _FD_DUP_REDIRECT_TARGET_RE.match(target):
        return None
    return target


def _tool_input(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("tool_input") or payload.get("toolInput") or {}
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
    payload: Mapping[str, Any], *, fallback: str = "",
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
            value for value in project_candidates
            if isinstance(value, str) and value.strip()
            and Path(value).expanduser() != _APP_CONTAINER_ROOT
        ),
        "",
    )
    raw_cwd = payload.get("cwd")
    if isinstance(raw_cwd, str) and raw_cwd.strip():
        return project_cwd if Path(raw_cwd).expanduser() == _APP_CONTAINER_ROOT else raw_cwd
    return project_cwd or fallback


def _resolve_target_paths(paths: List[str], cwd: str) -> List[str]:
    out: List[str] = []
    for raw in paths:
        path = Path(raw.strip()).expanduser()
        if path.is_absolute():
            out.append(str(path))
        elif cwd:
            out.append(str((Path(cwd).expanduser() / path).resolve()))
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


def extract_payload_targets(payload: Mapping[str, Any]) -> List[str]:
    """Return the list of target paths for a PreToolUse payload."""
    if not isinstance(payload, Mapping):
        return []
    tool_input = _tool_input(payload)

    out: List[str] = []

    file_path = tool_input.get("file_path")
    if isinstance(file_path, str) and file_path.strip():
        out.append(file_path)

    command = extract_payload_command(payload)
    if command:
        if _is_apply_patch_payload(payload):
            out.extend(parse_patch(command).all_paths())
        else:
            out.extend(extract_command_targets(command))

    cwd = resolve_payload_cwd(payload, fallback=str(Path.cwd()))
    return _dedupe_paths(_resolve_target_paths(out, cwd))


@dataclass(frozen=True)
class PayloadWriteTargets:
    """Write targets in a tool payload, plus what could not be resolved.

    ``unresolved_variable`` reports that the body wrote through a variable
    reference this layer could not expand. A caller that would otherwise
    fall back to the harness cwd must not do so on that signal: the write
    lands wherever the variable points, which is precisely what we failed
    to determine, so cwd is a manufactured verdict rather than a fallback.
    """

    targets: List[str]
    unresolved_variable: bool


def analyze_payload_write_targets(
    payload: Mapping[str, Any],
) -> PayloadWriteTargets:
    """Return write-position paths for a payload with resolution detail."""
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

    shell_targets, unresolved = _extract_shell_write_targets(command)
    out.extend(shell_targets)
    out.extend(analyze_python_heredoc_writes(command).targets)
    return PayloadWriteTargets(_dedupe_paths(out), unresolved)


def extract_payload_write_targets(payload: Mapping[str, Any]) -> List[str]:
    """Return only paths occupying real write positions in a tool payload."""
    return analyze_payload_write_targets(payload).targets


def payload_has_embedded_python_write(payload: Mapping[str, Any]) -> bool:
    """True when a Bash payload executes an embedded Python write call."""
    if not isinstance(payload, Mapping) or _is_apply_patch_payload(payload):
        return False
    command = extract_payload_command(payload)
    return bool(command) and analyze_python_heredoc_writes(command).detected


def _extract_shell_write_targets(command: str) -> Tuple[List[str], bool]:
    """Return write-position paths plus whether an expansion went unresolved.

    Variable bindings come from the whole command body, not the segment:
    the capture-first recipe assigns in one statement and redirects in the
    next, so a per-segment scan would never see the assignment.
    """
    bindings = shell_variable_bindings(command)
    out: List[str] = []
    unresolved = False
    for segment in split_pipeline(strip_heredoc_syntax(command)):
        try:
            tokens = strip_env_prefixes(shlex.split(segment))
        except ValueError:
            continue
        if not tokens:
            continue
        clean, redirects = _split_redirect_targets(tokens)
        resolved, segment_unresolved = resolve_write_operands(redirects, bindings)
        out.extend(resolved)
        unresolved = unresolved or segment_unresolved
        if not clean:
            continue
        command_base = PurePath(clean[0]).name
        if command_base == "git":
            out.extend(extract_command_targets(segment, bindings=bindings))
            continue
        args = clean[1:]
        positionals = [arg for arg in args if arg != "-" and not arg.startswith("-")]
        if command_base in _LAST_POSITIONAL_WRITE_COMMANDS and positionals:
            positionals = positionals[-1:]
        elif command_base not in _ALL_POSITIONAL_WRITE_COMMANDS:
            continue
        resolved, segment_unresolved = resolve_write_operands(positionals, bindings)
        out.extend(resolved)
        unresolved = unresolved or segment_unresolved
    return _dedupe_paths(out), unresolved


def _split_redirect_targets(tokens: List[str]) -> Tuple[List[str], List[str]]:
    clean: List[str] = []
    targets: List[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in REDIRECT_OPERATORS:
            if i + 1 < len(tokens):
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
    """Return the Bash command body from a PreToolUse payload, or ``""``.

    Surfaces the raw command so callers
    (:func:`extract_payload_targets`, the PYTHONPATH-equivalence
    override in :mod:`lint_session_cwd_control_plane`) can each parse it
    once without restating the payload-shape lookups.
    """
    if not isinstance(payload, Mapping):
        return ""
    tool_input = _tool_input(payload)
    command = tool_input.get("command") or tool_input.get("cmd")
    if not isinstance(command, str) and _is_apply_patch_payload(payload):
        for key in ("input", "patch", "diff"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                command = value
                break
    if not isinstance(command, str):
        command = payload.get("command")
    if isinstance(command, str) and command.strip():
        return command
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
