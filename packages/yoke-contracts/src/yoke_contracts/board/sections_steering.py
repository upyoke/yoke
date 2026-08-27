"""Steering-scope visibility for the generated board."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import project_id_filter, project_ref_where
from yoke_contracts.board.sections_sessions_rendering import (
    _aligned_table,
    _format_session_age,
)
from yoke_contracts.session_control.launch_origin import (
    LAUNCH_ORIGIN_STEERING_BACKSTOP,
)
from yoke_contracts.turn_end_evidence import STEERING_REPORT_IDEMPOTENCY_PREFIX


_STEERING_EMOJI = "\U0001f9ed"


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


def _active_claims(
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
                "claim_id": int(row[0]),
                "holder": str(row[1]),
                "project_id": project[0],
                "project": project[1],
                "claimed_at": row[3],
                "last_heartbeat": row[4],
                "last_tool_call_at": row[5],
                "ended_at": row[6],
                "terminated_at": row[7],
                "strategy_docs": [],
                "workers": 0,
                "reports": 0,
            }
        )
    return claims


def _claim_params(
    claims: list[dict[str, Any]],
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    return (
        tuple(int(claim["project_id"]) for claim in claims),
        tuple(str(claim["holder"]) for claim in claims),
    )


def _attach_documents(db: BoardDBLike, claims: list[dict[str, Any]]) -> None:
    if not claims:
        return
    projects, holders = _claim_params(claims)
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
    by_key = {(claim["project_id"], claim["holder"]): claim for claim in claims}
    for project_id, holder, slug in rows:
        claim = by_key.get((int(project_id), str(holder)))
        if claim:
            claim["strategy_docs"].append(str(slug))


def _attach_worker_counts(db: BoardDBLike, claims: list[dict[str, Any]]) -> None:
    if not claims:
        return
    projects, holders = _claim_params(claims)
    rows = _optional_query(
        db,
        "SELECT launch.project_id,launch.requester_session_id,"
        "COUNT(DISTINCT worker.session_id) "
        "FROM session_launches launch JOIN session_launch_attempts attempt "
        "ON attempt.launch_id=launch.launch_id JOIN harness_sessions worker "
        "ON worker.session_id=attempt.native_session_id "
        "WHERE launch.origin=%s AND launch.project_id IN ("
        + ",".join("%s" for _ in projects)
        + ") AND launch.requester_session_id IN ("
        + ",".join("%s" for _ in holders)
        + ") AND worker.ended_at IS NULL AND worker.terminated_at IS NULL "
        "GROUP BY launch.project_id,launch.requester_session_id",
        (LAUNCH_ORIGIN_STEERING_BACKSTOP, *projects, *holders),
    )
    by_key = {(claim["project_id"], claim["holder"]): claim for claim in claims}
    for project_id, holder, count in rows:
        claim = by_key.get((int(project_id), str(holder)))
        if claim:
            claim["workers"] = int(count or 0)


def _attach_report_counts(db: BoardDBLike, claims: list[dict[str, Any]]) -> None:
    if not claims:
        return
    projects, holders = _claim_params(claims)
    rows = _optional_query(
        db,
        "SELECT recipient.project_id,recipient.session_id,"
        "COUNT(DISTINCT recipient.message_id) "
        "FROM session_message_recipients recipient JOIN session_messages message "
        "ON message.message_id=recipient.message_id "
        "WHERE recipient.project_id IN ("
        + ",".join("%s" for _ in projects)
        + ") AND recipient.session_id IN ("
        + ",".join("%s" for _ in holders)
        + ") AND recipient.state IN ('pending','injected') "
        "AND message.idempotency_key LIKE %s "
        "GROUP BY recipient.project_id,recipient.session_id",
        (*projects, *holders, f"{STEERING_REPORT_IDEMPOTENCY_PREFIX}%"),
    )
    by_key = {(claim["project_id"], claim["holder"]): claim for claim in claims}
    for project_id, holder, count in rows:
        claim = by_key.get((int(project_id), str(holder)))
        if claim:
            claim["reports"] = int(count or 0)


def _holder_liveness(claim: dict[str, Any]) -> str:
    if claim["terminated_at"]:
        return "ended · killed"
    if claim["ended_at"]:
        return "ended"
    activity = max(
        str(claim["last_heartbeat"] or ""),
        str(claim["last_tool_call_at"] or ""),
    )
    return f"alive · {_format_session_age(activity)} activity"


def _scope_label(claim: dict[str, Any]) -> str:
    docs = claim["strategy_docs"]
    return str(claim["project"]) + (f" · {', '.join(docs)}" if docs else " · all docs")


def render_steering_section(db: BoardDBLike, scope: str) -> str:
    """Render every visible active steering scope, including an empty state."""
    claims = _active_claims(db, _projects(db, scope))
    _attach_documents(db, claims)
    _attach_worker_counts(db, claims)
    _attach_report_counts(db, claims)
    heading = f"### {_STEERING_EMOJI} Steering"
    if not claims:
        return f"{heading}\n\n_No active steering scopes in this board view._"
    rows = [
        [
            _scope_label(claim),
            f"`{claim['holder']}`",
            _format_session_age(str(claim["claimed_at"] or "")),
            _holder_liveness(claim),
            str(claim["workers"]),
            str(claim["reports"]),
        ]
        for claim in claims
    ]
    return "\n".join(
        [
            f"{heading} ({len(claims)})",
            "",
            *_aligned_table(
                ["Scope", "Holder", "Claim age", "Liveness", "Workers", "Reports"],
                rows,
            ),
        ]
    )


__all__ = ["render_steering_section"]
