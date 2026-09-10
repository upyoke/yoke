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
from yoke_harness.artifact_scan import iter_rows, tail_rows_newest_first
from yoke_harness.codex_artifact_reader import codex_record_decoder


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
    """Return the model the thread's newest turn names.

    The model is per-turn and the newest statement is the answer, so the
    read comes off the end of the transcript rather than walking a whole
    session's history to arrive at its last row.
    """
    for path in codex_transcript_candidates(thread_id):
        for row in tail_rows_newest_first(path, record_factory=codex_record_decoder):
            if row.get("type") != "turn_context":
                continue
            payload = row.get("payload") or {}
            model = payload.get("model")
            if model:
                return str(model)
    return None


def _codex_entrypoint_from_transcript(thread_id: str) -> Optional[str]:
    """Return the surface the thread's session metadata names.

    The entrypoint is stated once, in metadata written when the thread
    was created, and never changes — so the scan stops at the row that
    states it, and the answer is remembered for the thread. Reading past
    it, on every hook event of a session whose transcript keeps growing,
    is the whole cost this resolver used to pay for a value that was
    already settled.
    """
    remembered = _remembered_entrypoint(thread_id)
    if remembered:
        return remembered
    for path in codex_transcript_candidates(thread_id):
        for row in iter_rows(path, record_factory=codex_record_decoder):
            if row.get("type") != "session_meta":
                continue
            payload = row.get("payload") or {}
            entrypoint = _normalize_entrypoint(
                str(payload.get("originator") or ""),
                str(payload.get("source") or ""),
            )
            if entrypoint:
                _remember_entrypoint(thread_id, entrypoint)
                return entrypoint
    return None


def _entrypoint_cache_path(thread_id: str) -> Path:
    return (
        machine_config.cache_dir()
        / "codex-model-cache"
        / f"codex-entrypoint-{thread_id}.txt"
    )


def _remembered_entrypoint(thread_id: str) -> Optional[str]:
    try:
        remembered = _entrypoint_cache_path(thread_id).read_text(encoding="utf-8")
    except OSError:
        return None
    return remembered.strip() or None


def _remember_entrypoint(thread_id: str, entrypoint: str) -> None:
    """Persist immutable thread metadata, best effort — a miss costs a scan."""
    path = _entrypoint_cache_path(thread_id)
    staged = path.parent / f"{path.name}.{os.getpid()}.staged"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(f"{entrypoint}\n", encoding="utf-8")
        os.replace(staged, path)
    except OSError:
        try:
            staged.unlink()
        except OSError:
            return


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
    "_entrypoint_cache_path",
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
