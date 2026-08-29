"""Unified work-item roster with public references and live claim holders."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.item_page_claims import active_item_claims
from yoke_core.domain.workflow_runtime import workflow_runtime_from_row
from yoke_core.domain.schema_common import _column_exists, _table_exists


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def enrich_item_overview_rows(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add stored owner label, public reference, and active-claim facts.

    ``id`` stays whatever the underlying list projection emitted (its
    public ref); the numeric key is mirrored onto ``internal_id``. The
    owner cell degrades to empty when its actor cannot be rendered — an
    orphan actor never fails the roster.
    """
    from yoke_core.domain.actors import (
        ActorLabelAmbiguous,
        ActorLabelMissing,
        ActorNotFound,
    )
    from yoke_core.domain.actor_display import actor_display_name

    base_rows = [dict(row) for row in rows]
    ids = [int(row["internal_id"]) for row in base_rows]
    if not ids:
        return []
    conn = db_helpers.connect()
    try:
        marker = _p(conn)
        placeholders = ", ".join(marker for _ in ids)
        cursor = conn.execute(
            "SELECT i.id, i.owner, i.project_sequence, p.id AS project_id, "
            "p.slug AS project, p.name AS project_name, "
            "p.public_item_prefix "
            "FROM items i JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id IN ({placeholders})",
            tuple(ids),
        )
        facts = {int(row["id"]): row for row in _dict_rows(cursor)}
        owner_labels: dict[int, str] = {}
        for item_id, fact in facts.items():
            owner_raw = str(fact.get("owner") or "").strip()
            if (
                not owner_raw
                or owner_raw.lower() in ("none", "null")
            ):
                owner_labels[item_id] = ""
                continue
            try:
                actor_id = int(owner_raw)
            except ValueError:
                owner_labels[item_id] = owner_raw
                continue
            try:
                owner_labels[item_id] = actor_display_name(
                    conn, actor_id,
                )
            except (ActorNotFound, ActorLabelMissing, ActorLabelAmbiguous):
                owner_labels[item_id] = ""
        lane_cursor = conn.execute(
            "SELECT id, item_id, branch, path, lane_role, state, "
            "created_at, updated_at, released_at "
            "FROM item_worktrees "
            f"WHERE item_id IN ({placeholders}) AND state = 'active' "
            "ORDER BY item_id, id",
            tuple(ids),
        )
        worktrees: dict[int, list[dict[str, Any]]] = {}
        for lane in _dict_rows(lane_cursor):
            worktrees.setdefault(int(lane["item_id"]), []).append(lane)
        claims = active_item_claims(conn, ids)
        qa_attention: dict[int, dict[str, str]] = {}
        if (
            _table_exists(conn, "qa_requirements")
            and _table_exists(conn, "qa_runs")
            and _column_exists(conn, "qa_runs", "performed_by")
            and _column_exists(conn, "qa_runs", "verdict_reason")
        ):
            qa_cursor = conn.execute(
                "SELECT COALESCE(q.item_id,q.epic_id) AS item_id, "
                "r.verdict,r.verdict_reason FROM qa_requirements q "
                "JOIN qa_runs r ON r.id=(SELECT rr.id FROM qa_runs rr "
                "WHERE rr.qa_requirement_id=q.id ORDER BY rr.id DESC LIMIT 1) "
                f"WHERE COALESCE(q.item_id,q.epic_id) IN ({placeholders}) "
                "AND r.performed_by='agent' AND r.verdict='undetermined' "
                "ORDER BY r.id DESC",
                tuple(ids),
            )
            for attention in _dict_rows(qa_cursor):
                qa_attention.setdefault(int(attention["item_id"]), attention)
        version_ids = sorted({int(row["workflow_version_id"]) for row in base_rows})
        version_placeholders = ", ".join(marker for _ in version_ids)
        version_cursor = conn.execute(
            "SELECT v.id AS workflow_version_id, v.workflow_id, v.version, "
            "v.definition_json, v.definition_digest "
            "FROM workflow_versions v "
            f"WHERE v.id IN ({version_placeholders})",
            tuple(version_ids),
        )
        runtimes = {
            int(version["workflow_version_id"]): workflow_runtime_from_row(version)
            for version in _dict_rows(version_cursor)
        }
    finally:
        conn.close()

    result: list[dict[str, Any]] = []
    for row in base_rows:
        item_id = int(row["internal_id"])
        fact = facts[item_id]
        runtime = runtimes[int(row["workflow_version_id"])]
        row.update(
            {
                "public_ref": format_item_ref(
                    fact["project"],
                    fact["public_item_prefix"],
                    int(fact["project_sequence"]),
                ),
                "project_id": int(fact["project_id"]),
                "project": str(fact["project"]),
                "project_name": str(fact["project_name"]),
                "owner": owner_labels.get(item_id, ""),
                "claimed_by": claims.get(item_id),
                "worktrees": worktrees.get(item_id, []),
                "stage_label": runtime.stage_label(str(row["status"])),
                "qa_attention": qa_attention.get(item_id),
            }
        )
        result.append(row)
    return result


__all__ = ["enrich_item_overview_rows"]
