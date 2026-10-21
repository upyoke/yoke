"""Reuse one project's schedule pass across steering report pulls.

Computing the schedule is the costly part of a report, and a steering seat
pulls the report again within seconds: its watcher, its hook and its own
`yoke steering report get` all ask. The answer is reused for a short window
rather than recomputed per pull. A claim taken or released inside that
window shows on the next pull after it expires.

The cache is process-local. A server process serves one database at a
time, but a process can bind other authorities (`bound_pg_dsn`), so the key
carries the connection's database authority, the project and the session
whose claims the schedule evaluates. A connection without a stable
authority identity never shares an answer.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from time import monotonic
from typing import Any

from yoke_core.domain.steering_fleet_report_available import ScopeWork, scope_work

SCHEDULE_CACHE_SECONDS = 15
SCHEDULE_CACHE_LIMIT = 256
_CACHE: OrderedDict[tuple, tuple[float, ScopeWork]] = OrderedDict()
_CACHE_LOCK = Lock()


def _authority(conn: Any) -> tuple | None:
    info = getattr(conn, "info", None)
    if info is None:
        return None
    return (info.host, info.port, info.dbname, info.user)


def reused_scope_work(conn: Any, *, project_id: int, session_id: str) -> ScopeWork:
    """``scope_work`` for this project and session, at most a few seconds old."""
    authority = _authority(conn)
    if authority is None:
        return scope_work(conn, project_id=project_id, session_id=session_id)
    key = (authority, int(project_id), str(session_id))
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and monotonic() < cached[0]:
            _CACHE.move_to_end(key)
            return cached[1]
    work = scope_work(conn, project_id=project_id, session_id=session_id)
    with _CACHE_LOCK:
        _CACHE[key] = (monotonic() + SCHEDULE_CACHE_SECONDS, work)
        _CACHE.move_to_end(key)
        while len(_CACHE) > SCHEDULE_CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return work


def forget_reused_schedules() -> None:
    """Drop every remembered schedule pass."""
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = [
    "SCHEDULE_CACHE_SECONDS",
    "forget_reused_schedules",
    "reused_scope_work",
]
