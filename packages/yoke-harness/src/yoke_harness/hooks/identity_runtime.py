"""Product-safe hook executor, model, and cache probes."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from yoke_cli.config import machine_config


_CLAUDE_COARSE = "claude-code"
_CODEX_COARSE = "codex"
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
    return value.strip().lower() in _PLACEHOLDER_MODEL_VALUES


def is_codex(executor: Optional[str]) -> bool:
    if not executor:
        return False
    e = executor.strip().lower()
    return e == _CODEX_COARSE or e.startswith("codex-")


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


def _normalize_entrypoint(originator: str = "", source: str = "") -> Optional[str]:
    originator = originator.strip().lower()
    if originator:
        normalized = re.sub(r"[^a-z0-9]+", "-", originator).strip("-")
        if normalized:
            return normalized
    source = source.strip().lower()
    return source or None


def _codex_transcript_candidates(thread_id: str) -> list[Path]:
    roots = [
        Path.home() / ".codex" / "sessions",
        Path.home() / ".codex" / "archived_sessions",
    ]
    candidates: list[Path] = []
    for root in roots:
        if root.exists():
            candidates.extend(root.rglob(f"*{thread_id}.jsonl"))
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates


def _codex_model_from_transcript(thread_id: str) -> Optional[str]:
    for path in _codex_transcript_candidates(thread_id):
        model = ""
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if row.get("type") != "turn_context":
                        continue
                    payload = row.get("payload") or {}
                    model = payload.get("model") or model
        except Exception:
            continue
        if model:
            return model
    return None


def _codex_entrypoint_from_transcript(thread_id: str) -> Optional[str]:
    for path in _codex_transcript_candidates(thread_id):
        entrypoint = None
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if row.get("type") != "session_meta":
                        continue
                    payload = row.get("payload") or {}
                    entrypoint = _normalize_entrypoint(
                        str(payload.get("originator") or ""),
                        str(payload.get("source") or ""),
                    ) or entrypoint
        except Exception:
            continue
        if entrypoint:
            return entrypoint
    return None


def _runtime_cache_path(session_id: str) -> Path:
    return (
        machine_config.cache_dir()
        / "codex-model-cache"
        / f"codex-runtime-{session_id}.json"
    )


def resolve_session_id(stdin_data: str) -> str:
    return (
        os.environ.get("CODEX_THREAD_ID", "")
        or os.environ.get("YOKE_SESSION_ID", "")
        or _payload_field(stdin_data, "session_id")
    )


def write_runtime_cache(session_id: str, stdin_data: str) -> None:
    if not session_id or not stdin_data:
        return
    try:
        path = _runtime_cache_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            stdin_data if stdin_data.endswith("\n") else f"{stdin_data}\n",
            encoding="utf-8",
        )
    except OSError:
        return


def _cache_field(session_id: str, field: str) -> str:
    try:
        payload = json.loads(_runtime_cache_path(session_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    value = payload.get(field, "")
    return "" if value is None else str(value)


def _codex_resolve_model(thread_id: Optional[str] = None) -> Optional[str]:
    if os.environ.get("YOKE_MODEL"):
        return os.environ["YOKE_MODEL"]
    if os.environ.get("CODEX_MODEL"):
        return os.environ["CODEX_MODEL"]
    thread_id = thread_id or os.environ.get("CODEX_THREAD_ID", "")
    if not thread_id:
        return None
    return (
        _codex_model_from_transcript(thread_id)
        or _cache_field(thread_id, "model")
        or None
    )


def _codex_resolve_entrypoint(thread_id: Optional[str] = None) -> Optional[str]:
    env_entrypoint = _normalize_entrypoint(
        str(
            os.environ.get("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "")
            or os.environ.get("CODEX_ORIGINATOR", "")
        ),
        "",
    )
    if env_entrypoint:
        return env_entrypoint
    thread_id = thread_id or os.environ.get("CODEX_THREAD_ID", "")
    if not thread_id:
        return None
    return (
        _codex_entrypoint_from_transcript(thread_id)
        or _cache_field(thread_id, "entrypoint")
        or _normalize_entrypoint(_cache_field(thread_id, "originator"), "")
    )


def detect_executor() -> str:
    if os.environ.get("YOKE_EXECUTOR"):
        return os.environ["YOKE_EXECUTOR"]
    if os.environ.get("CODEX_THREAD_ID"):
        return _compose_executor(
            _CODEX_COARSE, _CODEX_COARSE, _codex_resolve_entrypoint(),
        )
    return _compose_executor(
        "claude", _CLAUDE_COARSE, os.environ.get("CLAUDE_CODE_ENTRYPOINT"),
    )


def detect_entrypoint() -> Optional[str]:
    val = os.environ.get("CLAUDE_CODE_ENTRYPOINT")
    if val:
        return val
    if os.environ.get("CODEX_THREAD_ID"):
        return _codex_resolve_entrypoint()
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
    if is_codex(executor or detect_executor()):
        return _codex_resolve_model() or "unknown"
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
    "_is_placeholder_model",
    "detect_entrypoint",
    "detect_executor",
    "detect_model",
    "is_codex",
    "resolve_session_id",
    "write_runtime_cache",
]
