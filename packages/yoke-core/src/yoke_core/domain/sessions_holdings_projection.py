"""Complete current-and-previous holdings projection for session cards."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from yoke_contracts.coordination_claim_keys import COORDINATION_TARGET_KINDS
from yoke_contracts.session_holdings import (
    SESSION_PATH_HOLDING_KEY,
    coordination_holding_key,
    group_session_holdings,
    strategy_document_holding_key,
    work_holding_key,
)
from yoke_core.domain import db_backend
from yoke_core.domain.coordination_claim_keys import key_for_target
from yoke_core.domain.sessions_holdings_claim_facts import (
    claimed_item_facts,
    clear_failed_read,
    steered_document_slugs,
)
from yoke_core.domain.sessions_holdings_claim_rows import all_claim_rows
from yoke_core.domain.sessions_holdings_read import render_claim_target
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_MIGRATION_SERIALIZATION,
    from_row as work_claim_target_from_row,
)


WEB_PREVIOUS_HOLDINGS_LIMIT = 3


def _row_dicts(rows: Iterable[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _claim_target_key(
    claim: Mapping[str, Any], rendered: str, document_slugs: Iterable[Any] = ()
) -> str:
    kind = str(claim.get("target_kind") or "")
    project_id = None
    if kind == "steering":
        project_id = work_claim_target_from_row(claim).project_id
    return work_holding_key(
        kind,
        item_id=claim.get("item_id"),
        epic_id=claim.get("epic_id"),
        task_num=claim.get("task_num"),
        process_key=claim.get("process_key"),
        project_id=project_id,
        steering_docs=document_slugs,
        rendered_target=rendered,
    )


def _item_claim_sessions(
    claims: Iterable[Mapping[str, Any]],
) -> tuple[dict[int, set[str]], dict[int, set[str]], dict[tuple[str, int], Any]]:
    historical: dict[int, set[str]] = {}
    current: dict[int, set[str]] = {}
    released_at: dict[tuple[str, int], Any] = {}
    for claim in claims:
        if claim.get("target_kind") != "item" or claim.get("item_id") is None:
            continue
        item_id = int(claim["item_id"])
        session_id = str(claim.get("session_id") or "")
        if not session_id:
            continue
        historical.setdefault(item_id, set()).add(session_id)
        if claim.get("released_at") is None:
            current.setdefault(item_id, set()).add(session_id)
        else:
            released_at.setdefault((session_id, item_id), claim.get("released_at"))
    return historical, current, released_at


def _work_observations(
    claims: list[dict[str, Any]],
    item_facts: Mapping[int, Mapping[str, Any]],
    steering_docs: Mapping[int, list[str]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        kind = str(claim.get("target_kind") or "")
        if kind in COORDINATION_TARGET_KINDS:
            continue
        session_id = str(claim.get("session_id") or "")
        if not session_id:
            continue
        target, facts = render_claim_target(claim, dict(item_facts))
        facts.pop("item_status", None)
        facts.pop("item_workflow_id", None)
        document_slugs: list[str] = []
        if kind == "steering" and facts.get("project_id") is not None:
            document_slugs = list(steering_docs.get(int(claim["id"]), []))
            facts["strategy_docs"] = document_slugs
        grouped.setdefault(session_id, []).append(
            {
                "holding_kind": "work_claim",
                "target_kind": kind,
                "target_key": _claim_target_key(claim, target, document_slugs),
                "target": target,
                "claimed_at": claim.get("claimed_at"),
                "released_at": claim.get("released_at"),
                **facts,
            }
        )
    return grouped


def _coordination_observations(
    claims: list[dict[str, Any]],
    item_facts: Mapping[int, Mapping[str, Any]],
    historical_item_sessions: Mapping[int, set[str]],
    current_item_sessions: Mapping[int, set[str]],
    item_releases: Mapping[tuple[str, int], Any],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        kind = str(claim.get("target_kind") or "")
        if kind not in COORDINATION_TARGET_KINDS:
            continue
        target = work_claim_target_from_row(claim)
        lease_key = key_for_target(target)
        base: dict[str, Any] = {
            "holding_kind": "coordination",
            "target_kind": kind,
            "target_key": coordination_holding_key(lease_key),
            "target": lease_key,
            "lease_key": lease_key,
            "owner_kind": "session",
            "claimed_at": claim.get("claimed_at"),
        }
        owner_item_id = (
            target.item_id if kind == TARGET_KIND_MIGRATION_SERIALIZATION else None
        )
        if owner_item_id is None:
            session_id = str(claim.get("session_id") or "")
            if session_id:
                grouped.setdefault(session_id, []).append(
                    {**base, "released_at": claim.get("released_at")}
                )
            continue
        item_id = int(owner_item_id)
        owner_facts = dict(item_facts.get(item_id) or {})
        for session_id in sorted(historical_item_sessions.get(item_id, set())):
            held = claim.get(
                "released_at"
            ) is None and session_id in current_item_sessions.get(item_id, set())
            grouped.setdefault(session_id, []).append(
                {
                    **base,
                    "owner_kind": "item",
                    "owner_item_id": item_id,
                    "owner_public_ref": owner_facts.get("public_ref"),
                    "released_at": (
                        None
                        if held
                        else claim.get("released_at")
                        or item_releases.get((session_id, item_id))
                        or "released"
                    ),
                }
            )
    return grouped


def _query_or_empty(conn: Any, sql: str) -> list[dict[str, Any]]:
    try:
        return _row_dicts(conn.execute(sql).fetchall())
    except db_backend.database_error_types(conn):
        clear_failed_read(conn)
        return []


def _path_rows(conn: Any) -> list[dict[str, Any]]:
    return _query_or_empty(
        conn,
        "SELECT pc.id,pc.owner_kind,pc.owner_item_id,pc.owner_session_id,"
        "pc.owner_work_claim_id,pc.released_at,pc.cancelled_at,"
        "(SELECT COUNT(*) FROM path_claim_targets pct "
        "WHERE pct.claim_id=pc.id) AS declared_count "
        "FROM path_claims pc ORDER BY pc.id DESC",
    )


def _path_observations(
    conn: Any,
    claims: list[dict[str, Any]],
    item_facts: Mapping[int, Mapping[str, Any]],
    historical_item_sessions: Mapping[int, set[str]],
    current_item_sessions: Mapping[int, set[str]],
    item_releases: Mapping[tuple[str, int], Any],
) -> dict[str, list[dict[str, Any]]]:
    claims_by_id = {int(claim["id"]): claim for claim in claims}
    buckets: dict[tuple[str, str, bool], dict[str, Any]] = {}

    def add(
        session_id: str, key: str, target: str, count: int, held: bool, released: Any
    ) -> None:
        bucket_key = (session_id, key, held)
        entry = buckets.setdefault(
            bucket_key,
            {
                "holding_kind": "path_claim",
                "target_kind": "path_claim",
                "target_key": key,
                "target": target,
                "path_count": 0,
                "released_at": None if held else released or "released",
            },
        )
        entry["path_count"] = int(entry["path_count"]) + count

    for row in _path_rows(conn):
        owner_kind = str(row.get("owner_kind") or "")
        terminal = row.get("released_at") or row.get("cancelled_at")
        count = int(row.get("declared_count") or 0)
        if owner_kind == "item" and row.get("owner_item_id") is not None:
            item_id = int(row["owner_item_id"])
            target = str((item_facts.get(item_id) or {}).get("public_ref") or item_id)
            for session_id in sorted(historical_item_sessions.get(item_id, set())):
                held = terminal is None and session_id in current_item_sessions.get(
                    item_id, set()
                )
                add(
                    session_id,
                    work_holding_key("item", item_id=item_id),
                    target,
                    count,
                    held,
                    terminal or item_releases.get((session_id, item_id)),
                )
        elif owner_kind == "session" and row.get("owner_session_id"):
            session_id = str(row["owner_session_id"])
            add(
                session_id,
                SESSION_PATH_HOLDING_KEY,
                "session files",
                count,
                terminal is None,
                terminal,
            )
        elif owner_kind == "process" and row.get("owner_work_claim_id") is not None:
            claim = claims_by_id.get(int(row["owner_work_claim_id"]))
            if not claim or not claim.get("session_id"):
                continue
            session_id = str(claim["session_id"])
            process_key = str(claim.get("process_key") or "process")
            held = terminal is None and claim.get("released_at") is None
            add(
                session_id,
                work_holding_key("process", process_key=process_key),
                f"process {process_key}",
                count,
                held,
                terminal or claim.get("released_at"),
            )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for (session_id, _key, _held), entry in buckets.items():
        grouped.setdefault(session_id, []).append(entry)
    return grouped


def _strategy_observations(conn: Any) -> dict[str, list[dict[str, Any]]]:
    rows = _query_or_empty(
        conn,
        "SELECT sdc.owner_session_id,sdc.project_id,sdc.strategy_doc_slug,"
        "sdc.released_at,p.slug AS project FROM strategy_doc_claims sdc "
        "JOIN projects p ON p.id=sdc.project_id "
        "WHERE sdc.owner_kind='session' "
        "ORDER BY CASE WHEN sdc.released_at IS NULL THEN 0 ELSE 1 END,"
        "sdc.released_at DESC,sdc.project_id,sdc.strategy_doc_slug",
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        session_id = str(row.get("owner_session_id") or "")
        if not session_id:
            continue
        project_id = int(row["project_id"])
        slug = str(row["strategy_doc_slug"])
        grouped.setdefault(session_id, []).append(
            {
                "holding_kind": "strategy_document",
                "target_kind": "strategy_document",
                "target_key": strategy_document_holding_key(project_id, slug),
                "target": f"{row['project']} · {slug}",
                "project_id": project_id,
                "strategy_doc": slug,
                "released_at": row.get("released_at"),
            }
        )
    return grouped


def session_holdings_by_session(
    conn: Any,
    *,
    previous_limit: int = WEB_PREVIOUS_HOLDINGS_LIMIT,
) -> dict[str, dict[str, Any]]:
    """Return the shared holdings model for every session with a holding."""
    claims = _row_dicts(all_claim_rows(conn))
    item_ids = [
        int(claim["item_id"])
        for claim in claims
        if claim.get("target_kind") == "item" and claim.get("item_id") is not None
    ]
    for claim in claims:
        if claim.get("target_kind") == TARGET_KIND_MIGRATION_SERIALIZATION:
            target = work_claim_target_from_row(claim)
            if target.item_id is not None:
                item_ids.append(int(target.item_id))
    item_facts = claimed_item_facts(conn, item_ids)
    historical, current, releases = _item_claim_sessions(claims)
    steering_docs = steered_document_slugs(
        conn,
        (
            int(claim["id"])
            for claim in claims
            if claim.get("target_kind") == "steering"
        ),
    )
    sources = [
        _work_observations(claims, item_facts, steering_docs),
        _path_observations(conn, claims, item_facts, historical, current, releases),
        _strategy_observations(conn),
        _coordination_observations(claims, item_facts, historical, current, releases),
    ]
    observations: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        for session_id, entries in source.items():
            observations.setdefault(session_id, []).extend(entries)
    result: dict[str, dict[str, Any]] = {}
    for session_id, entries in observations.items():
        grouped = group_session_holdings(entries, previous_limit=previous_limit)
        grouped["steered"] = any(
            str(entry.get("target_kind") or "") == "steering" for entry in entries
        )
        result[session_id] = grouped
    return result


__all__ = ["WEB_PREVIOUS_HOLDINGS_LIMIT", "session_holdings_by_session"]
