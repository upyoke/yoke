"""Cross-process cache for board activity day counts.

Day counts come from the ``item_activity_days`` state table (one row per
project/item/UTC-day touched by a real domain mutation — see
``yoke_core.domain.item_activity``). The cache invalidates on the
table's monotonic ``MAX(id)`` watermark: a new (project, item, day)
tuple always lands with a higher id, and upsert conflicts (same-day
re-touches) change nothing, so an equal watermark proves the counts are
current.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

from yoke_contracts.board.phase_timer import measure_phase
from yoke_contracts.board.project_scope import project_filter, visible_project_ids
from yoke_contracts.machine_config import runtime as machine_config


_CACHE_BASENAME = "board-activity-day-counts.json"
_CACHE_VERSION = 2  # v2: item_activity_days sourcing (events scan retired)


def _cache_path() -> Path:
    return machine_config.cache_dir() / _CACHE_BASENAME


def _cache_key(scope: str) -> str:
    ids = visible_project_ids()
    if ids is not None:
        return f"{scope}|visible:{','.join(str(project_id) for project_id in ids)}"
    return str(scope)


def _load_cache(path: Path) -> Dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": _CACHE_VERSION, "entries": {}}
    if not isinstance(raw, dict):
        return {"version": _CACHE_VERSION, "entries": {}}
    if raw.get("version") != _CACHE_VERSION:
        return {"version": _CACHE_VERSION, "entries": {}}
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        raw["entries"] = {}
    return raw


def _write_cache(path: Path, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _latest_activity_row_id(db: Any, scope: str) -> int:
    pf = project_filter(scope, "a")
    rows = db.query_quiet(
        "SELECT a.id FROM item_activity_days a "
        "WHERE 1=1 "
        f"{pf} "
        "ORDER BY a.id DESC LIMIT 1"
    )
    if not rows:
        return 0
    try:
        return int(rows[0][0] or 0)
    except (TypeError, ValueError):
        return 0


def _query_activity_day_counts(db: Any, scope: str) -> Dict[str, int]:
    pf = project_filter(scope, "a")
    sql = (
        "SELECT a.day AS day,"
        "       COUNT(DISTINCT a.item_id) AS cnt "
        "FROM item_activity_days a "
        "WHERE 1=1 "
        f"  {pf}"
        " GROUP BY a.day ORDER BY a.day"
    )
    rows = db.query_quiet(sql)
    counts: Dict[str, int] = {}
    for row in rows:
        if row[0]:
            counts[row[0]] = int(row[1])
    return counts


def activity_day_counts(db: Any, scope: str) -> Dict[str, int]:
    """Return activity counts by day, persisted across CLI invocations.

    A board-data recording handle (``db.record_mode``) bypasses the
    machine-local file cache entirely: the recorded payload must carry
    the day-counts query for any replay whose own local cache is stale,
    and the server's cache state must never shape the recorded plan.
    """
    recorder = getattr(db, "_phase_recorder", None)
    if getattr(db, "record_mode", False):
        # Replay consults the watermark before deciding cache freshness,
        # so the recording pass must execute (and record) both reads.
        _latest_activity_row_id(db, scope)
        return _query_activity_day_counts(db, scope)
    with measure_phase(recorder, "activity_cache_watermark"):
        latest_id = _latest_activity_row_id(db, scope)

    cache_path = _cache_path()
    key = _cache_key(scope)
    with measure_phase(recorder, "activity_cache_read"):
        cache = _load_cache(cache_path)
        entry = cache.get("entries", {}).get(key)

    if (
        isinstance(entry, dict)
        and int(entry.get("latest_row_id") or 0) == latest_id
        and isinstance(entry.get("counts"), dict)
    ):
        return {str(day): int(count) for day, count in entry["counts"].items()}

    with measure_phase(recorder, "activity_query"):
        counts = _query_activity_day_counts(db, scope)

    with measure_phase(recorder, "activity_cache_write"):
        entries = cache.setdefault("entries", {})
        entries[key] = {
            "scope": scope,
            "latest_row_id": latest_id,
            "updated_at": int(time.time()),
            "counts": counts,
        }
        _write_cache(cache_path, cache)
    return counts


__all__ = ["activity_day_counts"]
