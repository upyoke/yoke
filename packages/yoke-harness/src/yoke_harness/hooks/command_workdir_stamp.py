"""Stamp the directory a shell command runs in onto hook stdin, client-side.

The harness manifest's ``identity.command_workdir_source`` says where each
harness carries a command's workdir. Two sources already arrive in the
payload. ``rollout_exec_command_workdir`` (Codex) does not: hook stdin
carries ``{command}`` plus the session ``cwd``, while the per-call workdir
lives only in the session rollout at ``transcript_path`` — a file on this
machine that a relayed server cannot open. So the client reads it here and
writes ``tool_input.workdir`` before any evaluation, local or relayed.

One Codex ``exec`` call may run several ``exec_command`` invocations with
different workdirs. The stamped workdir belongs to the invocation whose
``cmd`` is this hook's command; when that cannot be told apart, nothing is
stamped and the guards resolve against the session cwd, never a neighbour's
directory.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_contracts.harness_command_workdir import (
    ROLLOUT_EXEC_COMMAND_WORKDIR,
    HARNESS_COMMAND_WORKDIR_SOURCES,
)
from yoke_contracts.executor_labels import canonical_harness_id

# Same bound as the Codex transcript observer — keep per-hook I/O capped.
_TRANSCRIPT_TAIL_BYTES = 2 * 1024 * 1024
_CALL_RE = re.compile(r"\bexec_command\s*\(\s*\{")
_KEY_RE = re.compile(r"""\s*(?:(["'])(\w+)\1|(\w+))\s*:\s*""")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def _read_string(text: str, pos: int) -> tuple[Optional[str], int]:
    """Decode a JS string literal at ``pos``; ``None`` when it is not one."""
    quote = text[pos] if pos < len(text) else ""
    if quote not in {'"', "'", "`"}:
        return None, pos
    out: list[str] = []
    i = pos + 1
    while i < len(text):
        ch = text[i]
        if ch == quote:
            return "".join(out), i + 1
        if quote == "`" and text.startswith("${", i):
            return None, i
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", text[i + 2 : i + 6]):
                out.append(chr(int(text[i + 2 : i + 6], 16)))
                i += 6
                continue
            if nxt == "x" and re.fullmatch(r"[0-9a-fA-F]{2}", text[i + 2 : i + 4]):
                out.append(chr(int(text[i + 2 : i + 4], 16)))
                i += 4
                continue
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return None, i


def _skip_value(text: str, pos: int) -> int:
    """Advance past one non-string value to the ``,`` or ``}`` ending it."""
    depth = 0
    i = pos
    while i < len(text):
        ch = text[i]
        if ch in "\"'`":
            _value, i = _read_string(text, i)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif ch == "," and depth == 0:
            return i
        i += 1
    return i


def exec_command_calls(source: str) -> list[dict[str, Optional[str]]]:
    """Return ``{cmd, workdir}`` for each ``exec_command({...})`` in ``source``."""
    calls: list[dict[str, Optional[str]]] = []
    for match in _CALL_RE.finditer(source):
        fields: dict[str, Optional[str]] = {"cmd": None, "workdir": None}
        pos = match.end()
        while pos < len(source):
            key = _KEY_RE.match(source, pos)
            if key is None:
                break
            name = key.group(2) or key.group(3)
            value, end = _read_string(source, key.end())
            if value is None:
                end = _skip_value(source, key.end())
            elif name in fields:
                fields[name] = value
            pos = end
            while pos < len(source) and source[pos] in " \t\r\n":
                pos += 1
            if pos >= len(source) or source[pos] != ",":
                break
            pos += 1
        calls.append(fields)
    return calls


def workdir_for_command(source: str, command: str) -> str:
    """Return the workdir of the invocation running ``command``, or ``""``."""
    calls = exec_command_calls(source)
    matched = [
        call for call in calls if call["cmd"] is not None and call["cmd"] == command
    ]
    if not matched and len(calls) == 1:
        matched = calls
    workdirs = {call["workdir"] or "" for call in matched}
    return workdirs.pop().strip() if len(workdirs) == 1 else ""


def rollout_call_source(transcript_path: str, tool_use_id: str) -> str:
    """Return the recorded input of the rollout call ``tool_use_id``."""
    if not transcript_path or not tool_use_id:
        return ""
    try:
        file_path = Path(transcript_path)
        size = file_path.stat().st_size
        with open(file_path, "rb") as handle:
            if size > _TRANSCRIPT_TAIL_BYTES:
                handle.seek(size - _TRANSCRIPT_TAIL_BYTES)
                handle.readline()
            chunk = handle.read()
    except OSError:
        return ""
    found = ""
    for raw in chunk.splitlines():
        if tool_use_id.encode() not in raw:
            continue
        try:
            payload = json.loads(raw).get("payload")
        except (ValueError, AttributeError, UnicodeDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if (payload.get("call_id") or payload.get("tool_use_id")) != tool_use_id:
            continue
        source = payload.get("input") or payload.get("arguments")
        if isinstance(source, str) and source:
            found = source
    return found


def _declares_workdir(
    payload: Mapping[str, Any], tool_input: Mapping[str, Any]
) -> bool:
    return any(
        isinstance(src.get(key), str) and src.get(key, "").strip()
        for src in (tool_input, payload)
        for key in ("workdir", "working_directory")
    )


def stamp_command_workdir(stdin_data: str, executor: str) -> str:
    """Return hook stdin with ``tool_input.workdir`` stamped when recoverable."""
    try:
        harness_id = canonical_harness_id(executor)
    except ValueError:
        return stdin_data
    source = HARNESS_COMMAND_WORKDIR_SOURCES.get(harness_id)
    if source != ROLLOUT_EXEC_COMMAND_WORKDIR or not stdin_data:
        return stdin_data
    try:
        payload = json.loads(stdin_data)
    except ValueError:
        return stdin_data
    if not isinstance(payload, dict):
        return stdin_data
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return stdin_data
    command = tool_input.get("command")
    if (
        not isinstance(command, str)
        or not command
        or _declares_workdir(payload, tool_input)
    ):
        return stdin_data
    call_source = rollout_call_source(
        str(payload.get("transcript_path") or ""),
        str(payload.get("tool_use_id") or ""),
    )
    workdir = workdir_for_command(call_source, command) if call_source else ""
    if not workdir:
        return stdin_data
    tool_input["workdir"] = workdir
    return json.dumps(payload)


__all__ = [
    "exec_command_calls",
    "rollout_call_source",
    "stamp_command_workdir",
    "workdir_for_command",
]
