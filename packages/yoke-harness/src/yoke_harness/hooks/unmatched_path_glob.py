"""Client-local unmatched path-glob evaluation."""

from __future__ import annotations

import glob
import re
from pathlib import Path

from yoke_harness.hooks.local_policy_common import DENY, NOOP, PolicyResult


_GLOB_CHARS = frozenset("*?[")
_REDIRECT_PREFIXES = ("2>>", ">>", "&>", "2>", "1>", ">", "<")
_HEREDOC = re.compile(
    r"<<(?P<strip>-)?\s*(?:'(?P<sq>[^']+)'|\"(?P<dq>[^\"]+)\"|(?P<bare>[A-Za-z_][A-Za-z0-9_]*))"
)


def _tool_input(payload: dict) -> dict:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _command(payload: dict) -> str:
    tool_input = _tool_input(payload)
    for source in (tool_input, payload):
        for key in ("command", "cmd"):
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _execution_cwd(payload: dict) -> str:
    tool_input = _tool_input(payload)
    for source in (tool_input, payload):
        for key in ("workdir", "working_directory"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value
    raw_cwd = payload.get("cwd")
    if isinstance(raw_cwd, str) and raw_cwd.strip():
        return raw_cwd
    for key in ("project_dir", "workspace"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    roots = payload.get("workspace_roots")
    if isinstance(roots, list):
        return next(
            (value for value in roots if isinstance(value, str) and value.strip()),
            "",
        )
    return ""


def _strip_heredoc_bodies(command: str) -> str:
    kept: list[str] = []
    delimiters: list[tuple[str, bool]] = []
    for line in command.splitlines(keepends=True):
        if delimiters:
            delimiter, strip_tabs = delimiters[0]
            candidate = line.rstrip("\r\n")
            if strip_tabs:
                candidate = candidate.lstrip("\t")
            if candidate == delimiter:
                delimiters.pop(0)
            continue
        kept.append(line)
        for match in _HEREDOC.finditer(line):
            delimiter = match.group("sq") or match.group("dq") or match.group("bare")
            delimiters.append((delimiter, bool(match.group("strip"))))
    return "".join(kept)


def _unquoted_tokens(command: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    in_single = in_double = escaped = False
    for char in _strip_heredoc_bodies(command):
        if escaped:
            if not in_single and not in_double:
                current.append(char)
            escaped = False
            continue
        if char == "\\" and not in_single:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if in_single or in_double:
            continue
        if char.isspace() or char in ";|&":
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def _unmatched(command: str, cwd: str) -> str:
    if not cwd:
        return ""
    for token in _unquoted_tokens(command):
        path = token
        for prefix in _REDIRECT_PREFIXES:
            if path.startswith(prefix):
                path = path[len(prefix) :]
                break
        if "/" not in path or not any(char in path for char in _GLOB_CHARS):
            continue
        pattern = path if path.startswith("/") else str(Path(cwd) / path)
        try:
            if not glob.glob(pattern):
                return path
        except (OSError, ValueError):
            continue
    return ""


def lint_unmatched_path_glob(payload: dict) -> PolicyResult:
    """Deny a Bash path glob that matches nothing on this client."""
    tool = payload.get("tool_name") or payload.get("toolName")
    if tool and tool != "Bash":
        return PolicyResult(NOOP)
    cwd = _execution_cwd(payload)
    token = _unmatched(_command(payload), cwd)
    if not token:
        return PolicyResult(NOOP)
    return PolicyResult(
        DENY,
        "BLOCKED: unquoted path glob matches no files under the command cwd.\n\n"
        f"Detected: `{token}`\nChecked tree: `{cwd}`\n\n"
        "zsh NOMATCH aborts the command before the tool runs. Enumerate "
        "candidates with `rg --files`, or quote a pattern the tool consumes.",
    )


__all__ = ["lint_unmatched_path_glob"]
