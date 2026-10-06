"""Read carried work, deriving live only for runs that have not finished.

A terminal run's answer cannot change, so a terminal run with no record —
one that finished before every terminal transition recorded it — is derived
once through the recorder and never again; a failed derivation is recorded by
name too, and ``deployment_runs.carried_work.repair`` replaces it. An
unfinished run is derived live behind a bounded process cache that amortizes
source walks across UI refreshes. That cache is presentation only; enrollment
and completion always use their own derivation. A striped single-flight lock
keeps concurrent cold reads in one process from deriving the same run twice;
the recorder's row lock does the same across processes.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from threading import Lock
from time import monotonic
from typing import Any, Mapping

from yoke_core.domain.deployment_run_carried_work import (
    derive_carried_work_safely,
    parse_carried_work,
    record_carried_work,
)
from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES


CACHE_SECONDS = 30
CACHE_RUN_LIMIT = 128
FLIGHT_LOCK_COUNT = 64
_CACHE: OrderedDict[tuple, tuple[float, dict[str, Any]]] = OrderedDict()
_CACHE_LOCK = Lock()
_FLIGHT_LOCKS = tuple(Lock() for _ in range(FLIGHT_LOCK_COUNT))


def _flight(key: tuple) -> Lock:
    return _FLIGHT_LOCKS[hash(key) % FLIGHT_LOCK_COUNT]


def _authority(conn: Any) -> tuple | None:
    info = getattr(conn, "info", None)
    if info is None:
        return None
    return (info.host, info.port, info.dbname, info.user)


def read_carried_work(conn: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    """Prefer the durable record; record a terminal run; cache a live one.

    Recording commits *conn*, so callers are read paths holding no pending
    writes of their own.
    """
    recorded = parse_carried_work(row.get("carried_work"))
    if recorded is not None:
        return recorded
    run_id = str(row["id"])
    authority = _authority(conn)
    if str(row.get("status") or "") in TERMINAL_RUN_STATUSES:
        with _flight((authority, run_id)):
            payload = record_carried_work(conn, run_id)
            conn.commit()
        return payload
    # Test doubles and non-Postgres validation connections have no stable
    # authority identity; do not share their answers across connections.
    if authority is None:
        return derive_carried_work_safely(conn, run_id)
    key = (
        *authority,
        run_id,
        row.get("release_lineage"),
        dumps_compact(row.get("bound_sources")),
        row.get("status"),
    )
    with _flight(key):
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached is not None and monotonic() < cached[0]:
                _CACHE.move_to_end(key)
                return deepcopy(cached[1])
        payload = derive_carried_work_safely(conn, run_id)
        with _CACHE_LOCK:
            _CACHE[key] = (monotonic() + CACHE_SECONDS, deepcopy(payload))
            _CACHE.move_to_end(key)
            while len(_CACHE) > CACHE_RUN_LIMIT:
                _CACHE.popitem(last=False)
    return payload


def compact_carried_work(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Keep item identities and named derivation outcomes for every project."""
    derivation = payload.get("derivation") or {}
    return {
        **{key: payload[key] for key in ("project_id", "project") if key in payload},
        "derivation": {
            key: derivation[key]
            for key in ("status", "contents_known", "reason", "recovery", "source")
            if key in derivation
        },
        "items": [
            {
                key: item[key]
                for key in ("ref", "title", "project_id", "project_sequence", "item_id")
                if item.get(key) not in (None, "")
            }
            for item in payload.get("items") or []
            if isinstance(item, dict)
        ],
        "commits": list(payload.get("commits") or []),
        "commit_subjects": dict(payload.get("commit_subjects") or {}),
        "commit_authors": dict(payload.get("commit_authors") or {}),
        "bound_projects": [
            compact_carried_work(project)
            for project in payload.get("bound_projects") or []
        ],
    }
