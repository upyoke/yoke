"""Codex runtime resolver — resolve active Codex metadata for a thread.

Extracted from the inline Python heredoc in ``resolve-model.sh``.

Resolution order:
  1. Explicit YOKE_MODEL override
  2. CODEX_MODEL env var
  3. Live/archived Codex session transcript for the thread ID
  4. SessionStart hook cache for this thread

Entrypoint resolution is similar, but first checks the live Codex runtime
environment for an originator string before falling back to transcript/cache.

Can be used as a module or invoked via CLI::

    python3 -m runtime.harness.codex.codex_model --thread-id THREAD_ID
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional


def _transcript_candidates(thread_id: str) -> list[Path]:
    """Return transcript candidates for a thread, newest first."""
    roots = [
        Path.home() / ".codex" / "sessions",
        Path.home() / ".codex" / "archived_sessions",
    ]

    candidates = []
    for root in roots:
        if not root.exists():
            continue
        candidates.extend(root.rglob(f"*{thread_id}.jsonl"))

    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates


def resolve_from_transcript(thread_id: str) -> Optional[str]:
    """Scan Codex session transcript JSONL files for the model."""
    candidates = _transcript_candidates(thread_id)

    for path in candidates:
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


def _normalize_entrypoint(originator: str = "", source: str = "") -> Optional[str]:
    """Return a stable entrypoint label from transcript metadata."""
    originator = originator.strip().lower()
    if originator:
        normalized = re.sub(r"[^a-z0-9]+", "-", originator).strip("-")
        if normalized:
            return normalized
    source = source.strip().lower()
    return source or None


def resolve_entrypoint_from_env() -> Optional[str]:
    """Resolve the entrypoint directly from Codex runtime env vars."""
    import os

    return _normalize_entrypoint(
        str(
            os.environ.get("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "")
            or os.environ.get("CODEX_ORIGINATOR", "")
        ),
        "",
    )


def resolve_entrypoint_from_transcript(thread_id: str) -> Optional[str]:
    """Scan Codex session transcript JSONL files for the entrypoint."""
    candidates = _transcript_candidates(thread_id)

    for path in candidates:
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


def _runtime_cache_path(thread_id: str) -> Path:
    """Return the helper-resolved Codex runtime cache path for a thread.

    Delegates to ``codex_hooks_payload.runtime_cache_path`` so the reader
    here and the writer that persists the SessionStart payload land on the
    same helper-resolved location under
    ``project_scratch_dir.storage_path('codex', 'model-cache', ...)``.
    """
    from runtime.harness.codex.codex_hooks_payload import runtime_cache_path

    return Path(runtime_cache_path(thread_id))


def resolve_from_cache(thread_id: str) -> Optional[str]:
    """Read the SessionStart hook cache file for a cached model."""
    cache_path = _runtime_cache_path(thread_id)
    if not cache_path.is_file():
        return None
    try:
        with cache_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        model = payload.get("model", "")
        return model if model else None
    except Exception:
        return None


def resolve_entrypoint_from_cache(thread_id: str) -> Optional[str]:
    """Read the SessionStart hook cache file for a cached entrypoint."""
    cache_path = _runtime_cache_path(thread_id)
    if not cache_path.is_file():
        return None
    try:
        with cache_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            return None
        entrypoint = payload.get("entrypoint", "")
        if entrypoint:
            return str(entrypoint)
        return _normalize_entrypoint(str(payload.get("originator") or ""), "")
    except Exception:
        return None


def resolve(thread_id: Optional[str] = None) -> Optional[str]:
    """Full resolution chain: env vars → transcript → cache.

    Returns the resolved model string, or None if no model can be found.
    """
    import os

    yoke_model = os.environ.get("YOKE_MODEL", "")
    if yoke_model:
        return yoke_model

    codex_model = os.environ.get("CODEX_MODEL", "")
    if codex_model:
        return codex_model

    if not thread_id:
        thread_id = os.environ.get("CODEX_THREAD_ID", "")

    if not thread_id:
        return None

    model = resolve_from_transcript(thread_id)
    if model:
        return model

    model = resolve_from_cache(thread_id)
    if model:
        return model

    return None


def resolve_entrypoint(thread_id: Optional[str] = None) -> Optional[str]:
    """Resolve the Codex session entrypoint, if the runtime exposes one."""
    import os

    entrypoint = resolve_entrypoint_from_env()
    if entrypoint:
        return entrypoint

    if not thread_id:
        thread_id = os.environ.get("CODEX_THREAD_ID", "")

    if not thread_id:
        return None

    entrypoint = resolve_entrypoint_from_transcript(thread_id)
    if entrypoint:
        return entrypoint

    entrypoint = resolve_entrypoint_from_cache(thread_id)
    if entrypoint:
        return entrypoint

    return None


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Resolve Codex model for a thread")
    parser.add_argument("--thread-id", default=None, help="Codex thread ID")
    args = parser.parse_args()

    model = resolve(thread_id=args.thread_id)
    if model:
        print(model)
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
