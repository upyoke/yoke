"""Codex-specific model/entrypoint resolution and runtime cache.

Codex names its model and entrypoint in thread transcripts under
``~/.codex/sessions`` (falling back to a per-session runtime cache written
at session start), so resolving either is a Codex-only concern. Split from
the shared identity module, which keeps the harness-neutral predicates and
detection chains and re-exports these resolvers for compatibility.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from yoke_cli.config import machine_config
from yoke_contracts.executor_labels import surface_alias


def _normalize_entrypoint(originator: str = "", source: str = "") -> Optional[str]:
    originator = originator.strip().lower()
    if originator:
        normalized = re.sub(r"[^a-z0-9]+", "-", originator).strip("-")
        if normalized:
            return normalized
    source = source.strip().lower()
    return source or None


#: Where Codex keeps the thread transcripts every reader here walks. The
#: relay's turn-record probe reads the same store, so the location lives
#: here once rather than once per caller.
CODEX_TRANSCRIPT_ROOT_NAMES = ("sessions", "archived_sessions")


def codex_transcript_roots() -> list[Path]:
    """Return Codex's transcript stores, newest-first search order."""
    home = Path.home() / ".codex"
    return [home / name for name in CODEX_TRANSCRIPT_ROOT_NAMES]


def codex_transcript_candidates(
    thread_id: str,
    *,
    roots: list[Path] | None = None,
) -> list[Path]:
    """Return one thread's transcripts, most recently written first."""
    candidates: list[Path] = []
    for root in roots if roots is not None else codex_transcript_roots():
        if root.exists():
            candidates.extend(root.rglob(f"*{thread_id}.jsonl"))
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates


def _codex_model_from_transcript(thread_id: str) -> Optional[str]:
    for path in codex_transcript_candidates(thread_id):
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
    for path in codex_transcript_candidates(thread_id):
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
                    entrypoint = (
                        _normalize_entrypoint(
                            str(payload.get("originator") or ""),
                            str(payload.get("source") or ""),
                        )
                        or entrypoint
                    )
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
        payload = json.loads(
            _runtime_cache_path(session_id).read_text(encoding="utf-8")
        )
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
    """Resolve the surface alias for this thread, the same from every path.

    The env originator is per-subprocess and the transcript's is
    session-level, so an invocation-context token in the environment yields
    to the thread's own identity: one physical surface must resolve to one
    ``executor_surface`` whether the session registers through a hook,
    the CLI's ensure-register probe, or session self-repair.
    """
    env_entrypoint = surface_alias(
        _normalize_entrypoint(
            str(
                os.environ.get("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "")
                or os.environ.get("CODEX_ORIGINATOR", "")
            ),
            "",
        )
    )
    if env_entrypoint:
        return env_entrypoint
    thread_id = thread_id or os.environ.get("CODEX_THREAD_ID", "")
    if not thread_id:
        return None
    return (
        surface_alias(_codex_entrypoint_from_transcript(thread_id))
        or surface_alias(_cache_field(thread_id, "entrypoint"))
        or surface_alias(
            _normalize_entrypoint(_cache_field(thread_id, "originator"), "")
        )
    )


__all__ = [
    "CODEX_TRANSCRIPT_ROOT_NAMES",
    "_cache_field",
    "_codex_entrypoint_from_transcript",
    "_codex_model_from_transcript",
    "_codex_resolve_entrypoint",
    "_codex_resolve_model",
    "codex_transcript_candidates",
    "codex_transcript_roots",
    "_normalize_entrypoint",
    "_runtime_cache_path",
    "write_runtime_cache",
]
