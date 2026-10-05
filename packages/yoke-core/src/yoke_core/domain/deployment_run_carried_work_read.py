"""Read current carried work without recording unfinished runs.

The bounded process cache amortizes source walks across UI refreshes. It is
presentation only; enrollment and completion always use their own derivation.
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
)
from yoke_core.domain.json_helper import dumps_compact


CACHE_SECONDS = 30
CACHE_RUN_LIMIT = 128
_CACHE: OrderedDict[tuple, tuple[float, dict[str, Any]]] = OrderedDict()
_CACHE_LOCK = Lock()


def read_carried_work(conn: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    """Prefer the durable record, otherwise derive with a short per-run cache."""
    recorded = parse_carried_work(row.get("carried_work"))
    if recorded is not None:
        return recorded
    info = getattr(conn, "info", None)
    # Test doubles and non-Postgres validation connections have no stable
    # authority identity; do not share their answers across connections.
    if info is None:
        return derive_carried_work_safely(conn, str(row["id"]))
    key = (
        info.host,
        info.port,
        info.dbname,
        info.user,
        str(row["id"]),
        row.get("release_lineage"),
        dumps_compact(row.get("bound_sources")),
        row.get("status"),
    )
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and monotonic() < cached[0]:
            _CACHE.move_to_end(key)
            return deepcopy(cached[1])
    payload = derive_carried_work_safely(conn, str(row["id"]))
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
