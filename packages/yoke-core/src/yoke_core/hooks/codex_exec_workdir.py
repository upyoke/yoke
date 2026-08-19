"""Recover the exec_command workdir Codex omits from PreToolUse stdin.

Codex honors ``exec_command.workdir`` at execution time but serializes
Bash hook stdin as ``{command}`` plus the session ``cwd``. The live
rollout still records the requested workdir on the matching
``custom_tool_call`` / ``call_id``. This module copies that value onto
``tool_input.workdir`` so ``resolve_payload_cwd`` can read it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

# Same bound as ``observe_codex_transcript`` — keep per-hook I/O capped.
_TRANSCRIPT_TAIL_BYTES = 2 * 1024 * 1024
_WORKDIR_RE = re.compile(r"""["']?workdir["']?\s*[:=]\s*['"]([^'"]+)['"]""")


def extract_exec_workdir(input_text: str) -> str:
    """Return the first ``workdir`` assignment in an exec_command body."""
    if not input_text:
        return ""
    match = _WORKDIR_RE.search(input_text)
    if match is None:
        return ""
    return match.group(1).strip()


def lookup_transcript_workdir(transcript_path: str, tool_use_id: str) -> str:
    """Return the exec workdir for ``tool_use_id``, or empty string."""
    if not transcript_path or not tool_use_id:
        return ""
    try:
        file_path = Path(transcript_path)
        if not file_path.is_file():
            return ""
        size = file_path.stat().st_size
        seek_pos = max(0, size - _TRANSCRIPT_TAIL_BYTES)
        with open(file_path, "rb") as handle:
            if seek_pos:
                handle.seek(seek_pos)
                handle.readline()
            chunk = handle.read()
    except OSError:
        return ""

    found = ""
    for raw in chunk.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            continue
        if not isinstance(obj, dict):
            continue
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            continue
        call_id = payload.get("call_id") or payload.get("tool_use_id")
        if call_id != tool_use_id:
            continue
        source = payload.get("input")
        if not isinstance(source, str):
            source = ""
        found = extract_exec_workdir(source) or found
    return found


def _payload_has_declared_workdir(payload: Mapping[str, Any]) -> bool:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    sources = (tool_input, payload) if isinstance(tool_input, Mapping) else (payload,)
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in ("workdir", "working_directory"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return True
    return False


def enrich_payload_workdir(payload: dict[str, Any]) -> dict[str, Any]:
    """Inject ``tool_input.workdir`` from the rollout when Codex omitted it."""
    if not payload or _payload_has_declared_workdir(payload):
        return payload
    workdir = lookup_transcript_workdir(
        str(payload.get("transcript_path") or ""),
        str(payload.get("tool_use_id") or ""),
    )
    if not workdir:
        return payload
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
        payload["tool_input"] = tool_input
    tool_input["workdir"] = workdir
    return payload


__all__ = [
    "enrich_payload_workdir",
    "extract_exec_workdir",
    "lookup_transcript_workdir",
]
