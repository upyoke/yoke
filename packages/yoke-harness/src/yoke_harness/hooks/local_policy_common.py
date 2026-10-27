"""Shared helpers for product-local hook policy evaluation."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional

from yoke_contracts.hook_runner.command_extract import extract_command


DENY = "deny"
ADVISORY = "advisory"
NOOP = "noop"


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
    return extract_command(payload)


def tool_name(payload: dict) -> str:
    for key in ("tool_name", "toolName"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def cwd_from_payload(payload: dict) -> str:
    data = tool_input(payload)
    for key in ("workdir", "working_directory"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
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


def repo_cwd(payload: dict, repo_path: str = "") -> str:
    return os.path.abspath(repo_path) if repo_path else cwd_from_payload(payload)


__all__ = [
    "ADVISORY",
    "DENY",
    "NOOP",
    "PolicyResult",
    "command_from_payload",
    "cwd_from_payload",
    "git",
    "repo_cwd",
    "response_text",
    "tool_name",
    "write_fields",
]
