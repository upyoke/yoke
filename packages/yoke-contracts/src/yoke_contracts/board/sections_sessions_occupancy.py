"""Project-slug and strategy-doc occupancy used by the sessions Claims column.

These reads match the query shapes the board collector already records for
visible projects and session-owned document locks, so replay can label
steering seats and ``doc:<SLUG>`` keycaps from a live payload.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import project_id_filter, project_ref_where

_OCCUPANCY_ATTR = "_session_occupancy"


def _optional_query(
    db: BoardDBLike,
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[tuple]:
    probe = getattr(db, "has_query_quiet", None)
    if callable(probe) and not probe(sql, params):
        return []
    return db.query_quiet(sql, params)


def _projects(db: BoardDBLike, scope: str) -> list[tuple[int, str]]:
    if scope == "all":
        clause, params = project_id_filter(prefix="WHERE")
    else:
        where, params = project_ref_where(scope)
        clause = f"WHERE {where}"
    return [
        (int(project_id), str(slug))
        for project_id, slug in _optional_query(
            db,
            f"SELECT id,slug FROM projects {clause} ORDER BY slug",
            params,
        )
    ]


def _scope_json(project_id: int) -> str:
    return json.dumps(
        {"project_id": int(project_id)},
        sort_keys=True,
        separators=(",", ":"),
    )


def _active_steering_holders(
    db: BoardDBLike,
    projects: list[tuple[int, str]],
) -> list[dict[str, Any]]:
    if not projects:
        return []
    scopes = {
        _scope_json(project_id): (project_id, slug) for project_id, slug in projects
    }
    markers = ",".join("%s" for _ in scopes)
    rows = _optional_query(
        db,
        "SELECT claim.id,claim.session_id,claim.scope,claim.claimed_at,"
        "holder.last_heartbeat,holder.last_tool_call_at,holder.ended_at,"
        "holder.terminated_at "
        "FROM work_claims claim LEFT JOIN harness_sessions holder "
        "ON holder.session_id=claim.session_id "
        "WHERE claim.target_kind='steering' AND claim.released_at IS NULL "
        f"AND claim.scope IN ({markers}) ORDER BY claim.claimed_at,claim.id",
        tuple(scopes),
    )
    claims: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        project = scopes.get(str(row[2]))
        if project is None or project[0] in seen:
            continue
        seen.add(project[0])
        claims.append(
            {
                "holder": str(row[1]),
                "project_id": project[0],
                "project": project[1],
            }
        )
    return claims


def _docs_by_session(
    db: BoardDBLike,
    claims: list[dict[str, Any]],
) -> dict[str, list[str]]:
    by_session: dict[str, list[str]] = {}
    if not claims:
        return by_session
    projects = tuple(int(claim["project_id"]) for claim in claims)
    holders = tuple(str(claim["holder"]) for claim in claims)
    rows = _optional_query(
        db,
        "SELECT project_id,owner_session_id,strategy_doc_slug "
        "FROM strategy_doc_claims WHERE owner_kind='session' "
        "AND released_at IS NULL AND project_id IN ("
        + ",".join("%s" for _ in projects)
        + ") AND owner_session_id IN ("
        + ",".join("%s" for _ in holders)
        + ") ORDER BY project_id,strategy_doc_slug",
        (*projects, *holders),
    )
    seen: set[tuple[str, str]] = set()
    for _project_id, holder, slug in rows:
        session_id = str(holder)
        name = str(slug)
        if not name or (session_id, name) in seen:
            continue
        seen.add((session_id, name))
        by_session.setdefault(session_id, []).append(name)
    return by_session


def prefetch_session_occupancy(db: BoardDBLike, scope: str) -> None:
    """Load visible project slugs and active session-owned document locks."""
    projects = _projects(db, scope)
    claims = _active_steering_holders(db, projects)
    setattr(
        db,
        _OCCUPANCY_ATTR,
        {
            "slugs": {project_id: slug for project_id, slug in projects},
            "docs": _docs_by_session(db, claims),
        },
    )


def occupancy_project_slug(db: BoardDBLike | None, project_id: int) -> str | None:
    if db is None:
        return None
    cache = getattr(db, _OCCUPANCY_ATTR, None)
    if not isinstance(cache, dict):
        return None
    slugs = cache.get("slugs")
    if not isinstance(slugs, dict):
        return None
    slug = slugs.get(int(project_id))
    return str(slug) if slug else None


def occupancy_doc_slugs(db: BoardDBLike | None, session_id: str) -> list[str] | None:
    if db is None:
        return None
    cache = getattr(db, _OCCUPANCY_ATTR, None)
    if not isinstance(cache, dict):
        return None
    docs = cache.get("docs")
    if not isinstance(docs, dict):
        return None
    found = docs.get(session_id)
    return list(found) if found else []


__all__ = [
    "occupancy_doc_slugs",
    "occupancy_project_slug",
    "prefetch_session_occupancy",
]
