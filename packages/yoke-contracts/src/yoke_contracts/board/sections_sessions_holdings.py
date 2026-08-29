"""Shared-model holdings projection for the BOARD.md session tables."""

from __future__ import annotations

import json
from typing import Any, List, Mapping, Optional, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import public_ref
from yoke_contracts.board.sections_sessions_claim_reads import (
    coordination_claims_for_session,
    path_claims_for_items,
    path_claims_for_session,
    strategy_doc_claims_for_session,
)
from yoke_contracts.board.sections_sessions_occupancy import occupancy_project_slug
from yoke_contracts.board.sections_sessions_rendering import (
    _claims_for_session,
    _render_claim_target,
)
from yoke_contracts.public_ref import format_item_ref
from yoke_contracts.session_holdings import (
    SESSION_PATH_HOLDING_KEY,
    coordination_holding_key,
    group_session_holdings,
    strategy_document_holding_key,
    work_holding_key,
)


PATH_GLYPH = "📁"
LEASE_GLYPH = "🔒"
PROCESS_GLYPH = "🔩"
STEERING_GLYPH = "🛞"
BOARD_PREVIOUS_HOLDINGS_LIMIT = 6


def _item_target(db: BoardDBLike, item_id: int) -> str:
    try:
        return public_ref(db, item_id)
    except Exception:
        return format_item_ref(None, None, None, item_id=item_id)


def _work_key(claim: Tuple, target: str) -> str:
    kind = str(claim[7] or "")
    scope = claim[9] if isinstance(claim[9], dict) else {}
    return work_holding_key(
        kind,
        item_id=claim[0],
        epic_id=claim[1],
        task_num=claim[2],
        process_key=claim[8],
        project_id=scope.get("project_id"),
        rendered_target=target,
    )


def _work_target(db: BoardDBLike, claim: Tuple) -> str:
    kind = str(claim[7] or "")
    if kind == "steering":
        scope = claim[9] if isinstance(claim[9], dict) else {}
        project_id = scope.get("project_id")
        slug = occupancy_project_slug(db, int(project_id)) if project_id else None
        return f"steering {slug or project_id or 'project'}"
    return _render_claim_target(
        claim[0],
        claim[1],
        claim[2],
        claim[8],
        db=db,
        target_kind=kind,
        scope=claim[9],
    )


def _work_observations(
    db: BoardDBLike,
    claims: List[Tuple],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[int]]:
    observations: list[dict[str, Any]] = []
    states: dict[str, dict[str, Any]] = {}
    item_ids: list[int] = []
    for claim in claims:
        target = _work_target(db, claim)
        key = _work_key(claim, target)
        released_at = claim[5]
        observations.append(
            {
                "holding_kind": "work_claim",
                "target_kind": str(claim[7] or ""),
                "target_key": key,
                "target": target,
                "claimed_at": claim[4],
                "released_at": released_at,
            }
        )
        state = states.setdefault(key, {"current": False, "released_at": None})
        if released_at is None:
            state["current"] = True
        elif state["released_at"] is None:
            state["released_at"] = released_at
        if claim[0] is not None and int(claim[0]) not in item_ids:
            item_ids.append(int(claim[0]))
    return observations, states, item_ids


def _process_anchor(db: BoardDBLike, work_claim_id: Optional[int]) -> Optional[str]:
    if work_claim_id is None:
        return None
    sql = "SELECT scope FROM work_claims WHERE id = %s AND target_kind = 'process'"
    params = (work_claim_id,)
    probe = getattr(db, "has_query_quiet", None)
    if callable(probe) and not probe(sql, params):
        return None
    rows = db.query_quiet(sql, params)
    if not rows:
        return None
    raw_scope = rows[0][0] if rows[0] else None
    try:
        scope = raw_scope if isinstance(raw_scope, dict) else json.loads(raw_scope)
    except (TypeError, ValueError):
        return None
    process_key = scope.get("process_key") if isinstance(scope, dict) else None
    return str(process_key) if process_key else None


def _path_observations(
    db: BoardDBLike,
    session_id: str,
    states: Mapping[str, Mapping[str, Any]],
    item_ids: List[int],
) -> list[dict[str, Any]]:
    facets: dict[tuple[str, bool], dict[str, Any]] = {}

    def add(
        key: str,
        target: str,
        count: int,
        terminal: Any,
        *,
        follows_work: bool,
    ) -> None:
        work_state = states.get(key) or {}
        held = terminal is None and (
            bool(work_state.get("current")) or not follows_work
        )
        released_at = (
            None if held else terminal or work_state.get("released_at") or "released"
        )
        bucket = facets.setdefault(
            (key, held),
            {
                "holding_kind": "path_claim",
                "target_kind": "path_claim",
                "target_key": key,
                "target": target,
                "path_count": 0,
                "released_at": released_at,
            },
        )
        bucket["path_count"] = int(bucket["path_count"]) + int(count or 0)

    for row in path_claims_for_items(db, item_ids):
        item_id = int(row[1])
        add(
            work_holding_key("item", item_id=item_id),
            _item_target(db, item_id),
            int(row[7] or 0),
            row[3] or row[4],
            follows_work=True,
        )
    for row in path_claims_for_session(db, session_id):
        process_key = _process_anchor(db, row[2])
        if process_key:
            add(
                work_holding_key("process", process_key=process_key),
                f"{PROCESS_GLYPH} {process_key}",
                int(row[7] or 0),
                row[3] or row[4],
                follows_work=True,
            )
        else:
            add(
                SESSION_PATH_HOLDING_KEY,
                "session files",
                int(row[7] or 0),
                row[3] or row[4],
                follows_work=False,
            )
    return list(facets.values())


def _strategy_observations(
    db: BoardDBLike,
    session_id: str,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for project_id, doc_slug, released_at in strategy_doc_claims_for_session(
        db, session_id
    ):
        slug = occupancy_project_slug(db, int(project_id)) or str(project_id)
        observations.append(
            {
                "holding_kind": "strategy_document",
                "target_kind": "strategy_document",
                "target_key": strategy_document_holding_key(project_id, doc_slug),
                "target": f"{slug} · {doc_slug}",
                "released_at": released_at,
            }
        )
    return observations


def _coordination_observations(
    db: BoardDBLike,
    session_id: str,
    states: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for row in coordination_claims_for_session(db, session_id):
        lease_key = str(row[1] or "?")
        terminal = row[2]
        owner_item_id = row[5] if len(row) > 5 else None
        owner_ref = None
        if owner_item_id is not None:
            work_state = states.get(
                work_holding_key("item", item_id=int(owner_item_id))
            )
            if work_state is None:
                continue
            held = terminal is None and bool(work_state.get("current"))
            terminal = terminal or (None if held else work_state.get("released_at"))
            owner_ref = _item_target(db, int(owner_item_id))
        observations.append(
            {
                "holding_kind": "coordination",
                "target_kind": row[4],
                "target_key": coordination_holding_key(lease_key),
                "target": lease_key,
                "owner_public_ref": owner_ref,
                "released_at": terminal,
            }
        )
    return observations


def _holding_label(entry: Mapping[str, Any]) -> str:
    kind = str(entry.get("holding_kind") or "")
    target = str(entry.get("target") or "?")
    if kind == "coordination":
        suffix = f" ({entry['owner_public_ref']})" if entry.get("owner_public_ref") else ""
        return f"{LEASE_GLYPH} {target}{suffix}"
    if kind == "strategy_document":
        return f"{STEERING_GLYPH} {target}"
    if kind == "path_claim":
        count = int(entry.get("path_count") or 0)
        return (
            f"{PATH_GLYPH}{count}"
            if target == "session files"
            else f"{target} {PATH_GLYPH}{count}"
        )
    if entry.get("target_kind") == "steering":
        target = f"{STEERING_GLYPH} {target}"
    if entry.get("path_count") is not None:
        target = f"{target} {PATH_GLYPH}{int(entry['path_count'])}"
    return target


def session_holding_labels(
    db: BoardDBLike,
    session_id: str,
    *,
    previous_limit: int = BOARD_PREVIOUS_HOLDINGS_LIMIT,
) -> List[str]:
    """Return current-first, globally deduplicated labels for one board row."""
    claims = _claims_for_session(db, session_id)
    work, states, item_ids = _work_observations(db, claims)
    observations = [
        *work,
        *_path_observations(db, session_id, states, item_ids),
        *_strategy_observations(db, session_id),
        *_coordination_observations(db, session_id, states),
    ]
    grouped = group_session_holdings(observations, previous_limit=previous_limit)
    labels = [_holding_label(entry) for entry in grouped["current"]]
    labels.extend(_holding_label(entry) for entry in grouped["previous"])
    if grouped["previous_remainder"]:
        labels.append(f"and {grouped['previous_remainder']} more")
    return labels


__all__ = [
    "BOARD_PREVIOUS_HOLDINGS_LIMIT",
    "LEASE_GLYPH",
    "PATH_GLYPH",
    "PROCESS_GLYPH",
    "STEERING_GLYPH",
    "session_holding_labels",
]
