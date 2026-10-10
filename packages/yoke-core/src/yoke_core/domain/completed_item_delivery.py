"""Completion-owned delivery attribution, stored in the existing rung facts.

Producer gates decide when an item may close. Their preflight stamp is not
completion: only the status transaction publishes completed deliveries. Readers
consume that durable answer and never re-evaluate a carrying run's mutable state.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.delivery_evidence_ladder import (
    SOURCE_CONTAINMENT,
    SOURCE_MEMBERSHIP,
)
from yoke_core.domain.gate_satisfier_ladder_catalog import OBLIGATION_DELIVERY_EVIDENCE
from yoke_core.domain.schema_common import _table_exists

COMPLETED_DELIVERIES = "completed_deliveries"


def registered_item_environments(
    conn: Any, item_ids: Iterable[int]
) -> set[tuple[int, str]]:
    ids = tuple(sorted(set(map(int, item_ids))))
    if not ids:
        return set()
    return {
        (int(row[0]), str(row[1]))
        for row in conn.execute(
            "SELECT i.id,e.name FROM items i JOIN environments e ON e.project_id=i.project_id "
            "WHERE i.id IN (" + ",".join("%s" for _ in ids) + ")",
            ids,
        ).fetchall()
    }


def completed_deliveries(conn: Any, item_ids: Iterable[int]) -> dict[int, list[dict]]:
    """One batched read of completed items and their attributed environments."""
    ids = tuple(sorted(set(map(int, item_ids))))
    if not ids or not _table_exists(conn, "item_gate_satisfactions"):
        return {}
    rows = conn.execute(
        "SELECT i.id,i.project_id,s.facts FROM items i "
        "JOIN item_gate_satisfactions s ON s.item_id=i.id "
        "WHERE i.status='done' AND s.obligation=%s AND i.id IN ("
        + ",".join("%s" for _ in ids)
        + ")",
        (OBLIGATION_DELIVERY_EVIDENCE, *ids),
    ).fetchall()
    projects = tuple(sorted({int(row[1]) for row in rows}))
    registered = set()
    if projects:
        registered = {
            (int(row[0]), int(row[1]), str(row[2]))
            for row in conn.execute(
                "SELECT id,project_id,name FROM environments WHERE project_id IN ("
                + ",".join("%s" for _ in projects)
                + ")",
                projects,
            ).fetchall()
        }
    result = {}
    for row in rows:
        item_id, project_id, raw = row
        facts = _facts(raw)
        entries = facts.get(COMPLETED_DELIVERIES, [])
        if not isinstance(entries, list):
            continue
        result[int(item_id)] = [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and entry.get("item_id") == int(item_id)
            and entry.get("project_id") == int(project_id)
            and (
                entry.get("member_item_id") == int(item_id)
                or (
                    entry.get("source") == SOURCE_CONTAINMENT
                    and entry.get("member_item_id") is None
                )
            )
            and entry.get("run_id")
            and entry.get("environment_id")
            and entry.get("environment")
            and entry.get("candidate")
            and (entry["environment_id"], entry["project_id"], entry["environment"])
            in registered
        ]
    return result


def _facts(raw: Any) -> dict:
    try:
        value = raw if isinstance(raw, dict) else json.loads(str(raw or "{}"))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _attribution(conn: Any, *, item_id: int, run_id: str, source: str) -> dict | None:
    from yoke_core.domain.deployment_run_project_sources import recorded_source_sha

    row = conn.execute(
        "SELECT dr.id,dr.project_id,dr.release_lineage,dr.bound_sources,"
        "e.id AS environment_id,e.name AS environment,i.project_id AS item_project_id,"
        "member.item_id AS member_item_id FROM deployment_runs dr "
        "JOIN environments target ON target.id=dr.target_environment_id "
        "JOIN items i ON i.id=%s "
        "JOIN environments e ON e.project_id=i.project_id AND e.name=target.name "
        "LEFT JOIN deployment_run_items member ON member.run_id=dr.id AND member.item_id=i.id "
        "WHERE dr.id=%s AND target.project_id=dr.project_id",
        (item_id, run_id),
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    candidate = recorded_source_sha(data, int(data["item_project_id"]))
    if not candidate or (
        source == SOURCE_MEMBERSHIP and data["member_item_id"] is None
    ):
        return None
    return {
        "item_id": item_id,
        "project_id": int(data["item_project_id"]),
        "run_project_id": int(data["project_id"]),
        "run_id": run_id,
        "member_item_id": data["member_item_id"],
        "environment_id": int(data["environment_id"]),
        "environment": str(data["environment"]),
        "candidate": candidate,
        "source": source,
    }


def _store(conn: Any, item_id: int, entries: list[dict]) -> None:
    """Update facts without committing or weakening a producer preflight."""
    row = conn.execute(
        "SELECT facts FROM item_gate_satisfactions WHERE item_id=%s AND obligation=%s FOR UPDATE",
        (item_id, OBLIGATION_DELIVERY_EVIDENCE),
    ).fetchone()
    facts = _facts(row[0]) if row else {}
    prior = facts.get(COMPLETED_DELIVERIES, [])
    by_identity = {
        (entry["run_id"], entry["environment_id"], entry["candidate"]): entry
        for entry in (prior if isinstance(prior, list) else []) + entries
    }
    facts[COMPLETED_DELIVERIES] = list(by_identity.values())
    encoded = json.dumps(facts, sort_keys=True)
    if row:
        conn.execute(
            "UPDATE item_gate_satisfactions SET facts=%s WHERE item_id=%s AND obligation=%s",
            (encoded, item_id, OBLIGATION_DELIVERY_EVIDENCE),
        )
    else:
        conn.execute(
            "INSERT INTO item_gate_satisfactions "
            "(item_id,obligation,rung_id,target_status,detail,facts,recorded_at) "
            "VALUES (%s,%s,'deployment_run_succeeded','done',%s,%s,%s)",
            (
                item_id,
                OBLIGATION_DELIVERY_EVIDENCE,
                "Delivery attribution committed with item completion",
                encoded,
                instant_parameter(conn, utc_now()),
            ),
        )


def record_completion_delivery(conn: Any, *, item_id: int) -> None:
    """Publish exact attribution in the successful done-write transaction."""
    from yoke_core.domain.delivery_evidence_ladder import delivery_evidence

    evidence = delivery_evidence(conn, item_id)
    if not evidence.discharged:
        # Merge-only completion has no environment attribution to publish.
        return
    entry = _attribution(
        conn, item_id=item_id, run_id=evidence.run_id, source=evidence.source
    )
    if entry is None:
        raise ValueError(
            "completion_delivery_unattributed: qualifying delivery has no exact "
            "run/member/environment/candidate; repair the run's registered target "
            "and recorded project source, then retry this item's close-out"
        )
    rows = conn.execute(
        "SELECT dr.id FROM deployment_runs dr JOIN deployment_run_items m ON m.run_id=dr.id "
        "WHERE m.item_id=%s AND dr.status='succeeded'",
        (item_id,),
    ).fetchall()
    entries = [entry]
    for row in rows:
        attributed = _attribution(
            conn, item_id=item_id, run_id=str(row[0]), source=SOURCE_MEMBERSHIP
        )
        if attributed:
            entries.append(attributed)
    _store(conn, item_id, entries)


def record_completed_run_delivery(conn: Any, *, run_id: str) -> None:
    """Attribute a later successful environment delivery to already-done members.

    This producer runs inside the success transaction, after shared gates. It
    lets a supplemental Stage release finish after Production closed the item.
    """
    rows = conn.execute(
        "SELECT i.id FROM items i JOIN deployment_run_items m ON m.item_id=i.id "
        "JOIN deployment_runs dr ON dr.id=m.run_id "
        "WHERE m.run_id=%s AND i.status='done' AND dr.status='succeeded'",
        (run_id,),
    ).fetchall()
    for row in rows:
        item_id = int(row[0])
        entry = _attribution(
            conn, item_id=item_id, run_id=run_id, source=SOURCE_MEMBERSHIP
        )
        if entry is None:
            raise ValueError(
                "completion_delivery_unattributed: completed member has no recorded "
                "project source or registered environment; repair the run and retry success"
            )
        _store(conn, item_id, [entry])
