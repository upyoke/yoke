"""Shared helpers for product-local hook policy evaluation."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional


DENY = "deny"
ADVISORY = "advisory"
NOOP = "noop"
SEP_RE = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


@dataclass(frozen=True)
class PolicyResult:
    outcome: str
    message: str = ""
    additional_context: str = ""


def tool_input(payload: dict) -> dict:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def command_from_payload(payload: dict) -> str:
    data = tool_input(payload)
    for key in ("command", "cmd"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    value = payload.get("command")
    return value if isinstance(value, str) else ""


def tool_name(payload: dict) -> str:
    for key in ("tool_name", "toolName"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def cwd_from_payload(payload: dict) -> str:
    for key in ("cwd", "workspace", "project_dir"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return os.getcwd()


def write_fields(payload: dict) -> tuple[str, str]:
    data = tool_input(payload)
    file_path = data.get("file_path") or data.get("filePath") or ""
    content = data.get("content") or data.get("body") or ""
    return (
        file_path if isinstance(file_path, str) else "",
        content if isinstance(content, str) else "",
    )


def response_text(payload: dict) -> str:
    response = payload.get("tool_response")
    if isinstance(response, dict):
        content = response.get("content", "")
        if isinstance(content, list):
            return " ".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in content
            )
        return content if isinstance(content, str) else str(content)
    return response if isinstance(response, str) else str(response or "")


def statements(command: str) -> list[list[str]]:
    out: list[list[str]] = []
    for stmt in SEP_RE.split(command or ""):
        if not stmt.strip():
            continue
        try:
            tokens = shlex.split(stmt, posix=True)
        except ValueError:
            continue
        index = 0
        while index < len(tokens) and ENV_RE.match(tokens[index]):
            index += 1
        if index < len(tokens):
            out.append(tokens[index:])
    return out


def git(cwd: str, *args: str) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def git_invocations(command: str) -> list[tuple[list[str], str]]:
    out: list[tuple[list[str], str]] = []
    for tokens in statements(command):
        index = 0
        if tokens[index].rsplit("/", 1)[-1] != "git":
            continue
        index += 1
        repo_path = ""
        while index < len(tokens):
            token = tokens[index]
            if token == "-C" and index + 1 < len(tokens):
                repo_path = tokens[index + 1]
                index += 2
            elif token.startswith("-C") and len(token) > 2:
                repo_path = token[2:]
                index += 1
            elif token == "-c" and index + 1 < len(tokens):
                index += 2
            elif token.startswith("-"):
                index += 1
            else:
                break
        if index < len(tokens):
            out.append((tokens[index:], repo_path))
    return out


def repo_cwd(payload: dict, repo_path: str = "") -> str:
    return os.path.abspath(repo_path) if repo_path else cwd_from_payload(payload)


def branch(cwd: str) -> str:
    result = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout.strip() if result and result.returncode == 0 else ""


def staged(cwd: str) -> list[str]:
    result = git(cwd, "diff", "--cached", "--name-only")
    if not result or result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def porcelain(cwd: str) -> tuple[list[str], list[str]]:
    result = git(cwd, "status", "--porcelain", "--untracked-files=all")
    if not result or result.returncode != 0:
        return [], []
    modified: list[str] = []
    untracked: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        if line[:2] == "??":
            untracked.append(line[3:])
        else:
            modified.append(line[3:].split(" -> ")[-1])
    return modified, untracked


__all__ = [
    "ADVISORY",
    "DENY",
    "NOOP",
    "PolicyResult",
    "branch",
    "command_from_payload",
    "cwd_from_payload",
    "git",
    "git_invocations",
    "porcelain",
    "repo_cwd",
    "response_text",
    "staged",
    "statements",
    "tool_name",
    "write_fields",
]
