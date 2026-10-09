"""Attribute historical completed deliveries from durable membership records.

Historical preflight stamps omitted run identity. Succeeded memberships are
authoritative; an independent-member stamp identifies its newest selected-flow
membership as the best available historical estimate. Future completions write
exact attribution atomically with done. Telemetry is never an input.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.deployment_run_project_sources import recorded_source_sha


def apply(conn: Any) -> None:
    if not all(
        _table_exists(conn, name)
        for name in (
            "items",
            "item_gate_satisfactions",
            "deployment_runs",
            "deployment_run_items",
            "environments",
        )
    ):
        return
    rows = conn.execute(
        "SELECT i.id,i.project_id,i.deployment_flow,s.facts,s.rung_id,s.recorded_at,"
        "dr.id AS run_id,dr.project_id AS run_project_id,dr.release_lineage,dr.bound_sources,"
        "dr.status AS run_status,dr.flow,e.id AS environment_id,e.name AS environment "
        "FROM items i JOIN deployment_run_items m ON m.item_id=i.id "
        "JOIN deployment_runs dr ON dr.id=m.run_id "
        "JOIN environments target ON target.id=dr.target_environment_id AND target.project_id=dr.project_id "
        "JOIN environments e ON e.name=target.name AND e.project_id=i.project_id "
        "LEFT JOIN item_gate_satisfactions s ON s.item_id=i.id AND s.obligation='delivery_evidence' "
        "WHERE i.status='done' ORDER BY i.id,dr.created_at DESC,dr.id DESC"
    ).fetchall()
    by_item: dict[int, dict] = {}
    independent: set[int] = set()
    for row in rows:
        data = dict(row)
        item_id = int(data["id"])
        saved = by_item.setdefault(
            item_id,
            {
                "facts": json.loads(str(data["facts"] or "{}")),
                "recorded_at": data["recorded_at"],
                "entries": [],
            },
        )
        qualifying = data["run_status"] == "succeeded"
        if (
            not qualifying
            and item_id not in independent
            and (
                data["rung_id"] == "independent_member_delivered"
                and data["flow"] == data["deployment_flow"]
            )
        ):
            qualifying = True
            independent.add(item_id)
        if not qualifying:
            continue
        candidate = recorded_source_sha(
            {
                "project_id": data["run_project_id"],
                "release_lineage": data["release_lineage"],
                "bound_sources": data["bound_sources"],
            },
            int(data["project_id"]),
        )
        saved["entries"].append(
            {
                "item_id": item_id,
                "member_item_id": item_id,
                "project_id": int(data["project_id"]),
                "run_project_id": int(data["run_project_id"]),
                "run_id": str(data["run_id"]),
                "environment_id": int(data["environment_id"]),
                "environment": str(data["environment"]),
                "candidate": candidate or "unrecorded",
                "source": "run_membership",
                "precision": "historical",
            }
        )
    for item_id, saved in by_item.items():
        if not saved["entries"]:
            continue
        facts = saved["facts"]
        # An exact producer can have published before this migration runs.
        # Keep those entries when the same attribution already exists.
        entries = saved["entries"] + facts.get("completed_deliveries", [])
        facts["completed_deliveries"] = list(
            {
                (entry["run_id"], entry["environment_id"], entry["candidate"]): entry
                for entry in entries
            }.values()
        )
        conn.execute(
            "INSERT INTO item_gate_satisfactions(item_id,obligation,rung_id,target_status,detail,facts,recorded_at) "
            "VALUES (%s,'delivery_evidence','deployment_run_succeeded','done',%s,%s,%s) "
            "ON CONFLICT(item_id,obligation) DO UPDATE SET facts=EXCLUDED.facts",
            (
                item_id,
                "Historical completed delivery attribution",
                json.dumps(facts, sort_keys=True),
                saved["recorded_at"] or "1970-01-01T00:00:00Z",
            ),
        )


def invariants(conn: Any) -> None:
    """Require attribution identity to stay bound to its completed owner."""
    if not _table_exists(conn, "item_gate_satisfactions"):
        return
    rows = conn.execute(
        "SELECT item_id,facts FROM item_gate_satisfactions WHERE obligation='delivery_evidence'"
    ).fetchall()
    for item_id, raw in rows:
        for entry in json.loads(str(raw or "{}")).get("completed_deliveries", []):
            if entry["item_id"] != int(item_id) or not all(
                entry.get(key)
                for key in ("run_id", "environment_id", "project_id", "candidate")
            ):
                raise RuntimeError(
                    "completed_delivery_attribution_invalid: repair the owner-bound delivery "
                    "stamp from authoritative membership records before serving"
                )
