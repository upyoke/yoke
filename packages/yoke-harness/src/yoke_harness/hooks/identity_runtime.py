"""Product-safe hook executor, model, and cache probes.

Harness-family predicates, executor/provider/entrypoint detection, and
model resolution shared by every harness. Codex's transcript/cache
resolvers live in :mod:`yoke_harness.hooks.identity_codex_runtime` and are
re-exported here for compatibility.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from yoke_harness.hooks.identity_codex_runtime import (
    _codex_resolve_entrypoint,
    _codex_resolve_model,
    write_runtime_cache,
)


_CLAUDE_LEGACY = "claude"
_CLAUDE_COARSE = "claude-code"
_CODEX_COARSE = "codex"
_CURSOR_COARSE = "cursor"
_CURSOR_AGENT_ENV = "CURSOR_INVOKED_AS"
_CURSOR_AGENT_VALUE = "cursor-agent"
_CURSOR_TRANSCRIPT_ENV = "CURSOR_TRANSCRIPT_PATH"
_CURSOR_SURFACE_CLI = "cli"
_CURSOR_SURFACE_DESKTOP = "desktop"
_PLACEHOLDER_MODEL_VALUES = frozenset({"", "default", "auto", "unknown"})


def _parse_payload(stdin_data: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdin_data) if stdin_data else None
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _payload_field(stdin_data: str, field: str) -> str:
    value = _parse_payload(stdin_data).get(field, "")
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _is_placeholder_model(value: object) -> bool:
    if not isinstance(value, str):
        return True
    normalized = value.strip().lower()
    if normalized in _PLACEHOLDER_MODEL_VALUES:
        return True
    return normalized.startswith("<") and normalized.endswith(">")


def is_codex(executor: Optional[str]) -> bool:
    if not executor:
        return False
    e = executor.strip().lower()
    return e == _CODEX_COARSE or e.startswith("codex-")


def is_cursor(executor: Optional[str]) -> bool:
    if not executor:
        return False
    e = executor.strip().lower()
    return e == _CURSOR_COARSE or e.startswith("cursor-")


def is_claude(executor: Optional[str]) -> bool:
    if not executor:
        return False
    e = executor.strip().lower()
    return e in {_CLAUDE_LEGACY, _CLAUDE_COARSE} or e.startswith("claude-")


def canonical_harness_id(executor: Optional[str]) -> str:
    if not executor or not executor.strip():
        raise ValueError("canonical_harness_id requires a non-empty executor")
    e = executor.strip().lower()
    if is_codex(e):
        return _CODEX_COARSE
    if is_cursor(e):
        return _CURSOR_COARSE
    if is_claude(e):
        return _CLAUDE_COARSE
    raise ValueError(f"unknown harness executor: {executor!r}")


def _normalize_surface_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def _compose_executor(family: str, coarse: str, raw_entrypoint: Optional[str]) -> str:
    if not raw_entrypoint:
        return coarse
    normalized = _normalize_surface_token(raw_entrypoint)
    if not normalized:
        return coarse
    if normalized == coarse or normalized.startswith(f"{family}-"):
        return normalized
    return f"{family}-{normalized}"


def compose_executor_from_entrypoint(
    executor: Optional[str],
    entrypoint: Optional[str],
) -> str:
    value = (executor or "").strip()
    if is_codex(value):
        return _compose_executor("codex", _CODEX_COARSE, entrypoint)
    if is_cursor(value):
        return _compose_executor("cursor", _CURSOR_COARSE, entrypoint)
    if is_claude(value):
        return _compose_executor("claude", _CLAUDE_COARSE, entrypoint)
    return value


def cursor_surface_entrypoint() -> str:
    """Return the Cursor surface alias for the current hook process.

    ``CURSOR_INVOKED_AS=cursor-agent`` marks the standalone terminal agent;
    every other Cursor hook process is the IDE surface. This deliberately
    does NOT consult ``CURSOR_TRANSCRIPT_PATH``: that variable is absent for
    a session's first hook events, which is exactly when session
    registration runs, so keying the surface on it loses the alias on the
    IDE surface and leaves ``executor_display_name`` NULL.

    Callers that must first decide whether this is a Cursor process at all
    still gate on the env vars; this resolver only answers *which surface*.
    """
    surface = (
        _CURSOR_SURFACE_CLI
        if os.environ.get(_CURSOR_AGENT_ENV) == _CURSOR_AGENT_VALUE
        else _CURSOR_SURFACE_DESKTOP
    )
    return _compose_executor(_CURSOR_COARSE, _CURSOR_COARSE, surface)


def _in_cursor_process() -> bool:
    return bool(
        os.environ.get(_CURSOR_TRANSCRIPT_ENV) or os.environ.get(_CURSOR_AGENT_ENV)
    )


def resolve_session_id(stdin_data: str) -> str:
    return (
        os.environ.get("CODEX_THREAD_ID", "")
        or os.environ.get("YOKE_SESSION_ID", "")
        or _payload_field(stdin_data, "session_id")
    )


def detect_executor() -> str:
    if os.environ.get("YOKE_EXECUTOR"):
        return os.environ["YOKE_EXECUTOR"]
    if os.environ.get("CODEX_THREAD_ID"):
        return _compose_executor(
            _CODEX_COARSE, _CODEX_COARSE, _codex_resolve_entrypoint(),
        )
    # Cursor exports no session env var; hook processes carry
    # CURSOR_TRANSCRIPT_PATH and the standalone terminal agent sets
    # CURSOR_INVOKED_AS=cursor-agent. The rendered Cursor hook command pins
    # YOKE_EXECUTOR=cursor, so this branch covers unpinned subprocesses.
    if _in_cursor_process():
        return cursor_surface_entrypoint()
    return _compose_executor(
        "claude", _CLAUDE_COARSE, os.environ.get("CLAUDE_CODE_ENTRYPOINT"),
    )


def detect_provider(executor: Optional[str] = None) -> str:
    # Cursor multiplexes providers (Anthropic, OpenAI, or Cursor-hosted
    # models within one session, named per hook payload), so its family
    # maps to "cursor" rather than a model vendor.
    if os.environ.get("YOKE_PROVIDER"):
        return os.environ["YOKE_PROVIDER"]
    resolved = executor or detect_executor()
    if is_codex(resolved):
        return "openai"
    if is_cursor(resolved):
        return "cursor"
    return "anthropic"


def detect_entrypoint() -> Optional[str]:
    val = os.environ.get("CLAUDE_CODE_ENTRYPOINT")
    if val:
        return val
    if os.environ.get("CODEX_THREAD_ID"):
        return _codex_resolve_entrypoint()
    if _in_cursor_process():
        return cursor_surface_entrypoint()
    return None


def _read_parent_argv() -> list[str]:
    try:
        ppid = os.getppid()
    except OSError:
        return []
    if ppid <= 1:
        return []
    try:
        result = subprocess.run(
            ["ps", "-p", str(ppid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []
    if result.returncode != 0:
        return []
    return result.stdout.strip().split()


def _extract_model_from_argv(argv: list[str]) -> str:
    for index, arg in enumerate(argv):
        if arg == "--model" and index + 1 < len(argv):
            val = argv[index + 1]
            return "" if _is_placeholder_model(val) else val
        if arg.startswith("--model="):
            val = arg[len("--model="):]
            return "" if _is_placeholder_model(val) else val
    return ""


def _read_model_from_transcript(transcript_path: Optional[str]) -> str:
    if not transcript_path or not os.path.isfile(transcript_path):
        return ""
    try:
        raw = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in reversed(raw.splitlines()[-500:]):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(entry, dict):
            continue
        msg = entry.get("message")
        if isinstance(msg, dict):
            model = msg.get("model")
            if isinstance(model, str) and not _is_placeholder_model(model):
                return model
    return ""


def detect_model(
    executor: Optional[str] = None,
    transcript_path: Optional[str] = None,
) -> str:
    if os.environ.get("YOKE_MODEL"):
        return os.environ["YOKE_MODEL"]
    resolved_executor = executor or detect_executor()
    if is_codex(resolved_executor):
        return _codex_resolve_model() or "unknown"
    if is_cursor(resolved_executor):
        # Cursor names the active model only inside each hook payload
        # (model/model_id fields); session registration passes it from the
        # payload explicitly. Without a payload in scope there is no
        # truthful ambient source.
        return "unknown"
    claude_env = os.environ.get("CLAUDE_MODEL", "")
    if claude_env and not _is_placeholder_model(claude_env):
        return claude_env
    argv_model = _extract_model_from_argv(_read_parent_argv())
    if argv_model:
        return argv_model
    transcript_model = _read_model_from_transcript(transcript_path)
    if transcript_model:
        return transcript_model
    default_env = os.environ.get("DEFAULT_LLM_MODEL", "")
    if default_env and not _is_placeholder_model(default_env):
        return default_env
    return "unknown"


__all__ = [
    "_codex_resolve_entrypoint",
    "_codex_resolve_model",
    "_compose_executor",
    "_is_placeholder_model",
    "_normalize_surface_token",
    "canonical_harness_id",
    "compose_executor_from_entrypoint",
    "detect_entrypoint",
    "detect_executor",
    "detect_model",
    "detect_provider",
    "is_claude",
    "is_codex",
    "is_cursor",
    "resolve_session_id",
    "write_runtime_cache",
]
