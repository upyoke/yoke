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
* **Bash:** parse the command body and surface any of:
    - ``-C <path>`` (git, make, etc.)
    - ``--rootdir <path>`` / ``--rootdir=<path>`` (pytest)
    - ``--target-root <path>`` / ``--target-root=<path>``
    - ``--worktree-path <path>`` / ``--worktree-path=<path>``
    - ``-w <path>`` (custom Yoke flag)
    - absolute-path positional arguments
* **No extractable target:** the caller falls back to the harness cwd.

This is intentionally narrow. Broad "every absolute path in the
command" extraction would surface system binaries (``/usr/bin/python3``)
and conflate command paths with target paths; the spec body names the
specific shapes above so per-flag extraction stays explicit.
"""

from __future__ import annotations

from typing import Any, List, Mapping

from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    FLAG_BINARY,
    FLAG_EQUALS_PREFIXES,
    extract_command_targets,
)


def extract_payload_targets(payload: Mapping[str, Any]) -> List[str]:
    """Return the list of target paths for a PreToolUse payload."""
    if not isinstance(payload, Mapping):
        return []
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool_input, Mapping):
        tool_input = {}

    out: List[str] = []

    file_path = tool_input.get("file_path")
    if isinstance(file_path, str) and file_path.strip():
        out.append(file_path)

    command = extract_payload_command(payload)
    if command:
        out.extend(extract_command_targets(command))

    seen: set[str] = set()
    deduped: List[str] = []
    for raw in out:
        key = raw.strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(raw)
    return deduped


def extract_payload_command(payload: Mapping[str, Any]) -> str:
    """Return the Bash command body from a PreToolUse payload, or ``""``.

    Surfaces the raw command so callers
    (:func:`extract_payload_targets`, the PYTHONPATH-equivalence
    override in :mod:`lint_session_cwd_control_plane`) can each parse it
    once without restating the payload-shape lookups.
    """
    if not isinstance(payload, Mapping):
        return ""
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool_input, Mapping):
        tool_input = {}
    command = tool_input.get("command") or tool_input.get("cmd")
    if not isinstance(command, str):
        command = payload.get("command")
    if isinstance(command, str) and command.strip():
        return command
    return ""


__all__ = [
    "FLAG_BINARY",
    "FLAG_EQUALS_PREFIXES",
    "extract_command_targets",
    "extract_payload_command",
    "extract_payload_targets",
]
