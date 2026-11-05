"""Resolve correction lineages independently of plans and execution receipts."""

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_deployment_case_correction_window import determinate_verdict


def base_case_key(key: str) -> str:
    """Return the authored key behind a content-addressed correction key."""
    return str(key).split("@", 1)[0]


def _included(row):
    return not row.get("retracted_at") or row.get("retraction_source") in {
        "operator",
        "agent",
    }


def lineage_heads(rows, seeds):
    """Return one newest chain end per connected component containing a seed.

    Both durable links are edges. Incoming edges join forks to their common
    root; unrelated plans with identical case keys remain separate components.
    """
    indexed = {int(row["id"]): dict(row) for row in rows if _included(row)}
    edges = {rid: set() for rid in indexed}
    outgoing = {rid: set() for rid in indexed}
    for rid, row in indexed.items():
        for field in ("replacement_requirement_id", "superseded_by_requirement_id"):
            successor = int(row.get(field) or 0)
            if successor in indexed:
                edges[rid].add(successor)
                edges[successor].add(rid)
                outgoing[rid].add(successor)
    seen, heads = set(), []
    for seed in seeds:
        rid = int(seed["id"])
        if rid not in indexed or rid in seen:
            continue
        component, pending = set(), [rid]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(edges[current] - component)
        seen.update(component)
        ends = [indexed[key] for key in component if not outgoing[key]]
        if not ends:
            raise ValueError(
                "replacement_graph_invalid: correction cycle; restore an acyclic "
                "chain through registered correction surfaces"
            )
        heads.append(
            max(
                ends, key=lambda row: (str(row.get("created_at") or ""), int(row["id"]))
            )
        )
    return heads


def connected_rows(conn, seeds):
    """Read both directions of durable links, including item QA lineages."""
    indexed = {int(row["id"]): dict(row) for row in seeds}
    pending = set(indexed)
    while pending:
        ids = sorted(pending)
        rows = query_rows(
            conn,
            "SELECT * FROM qa_requirements WHERE id=ANY(%s) "
            "OR replacement_requirement_id=ANY(%s) "
            "OR superseded_by_requirement_id=ANY(%s)",
            (ids, ids, ids),
        )
        pending = set()
        for row in rows:
            rid = int(row["id"])
            if rid not in indexed:
                pending.add(rid)
            indexed[rid] = dict(row)
            for field in ("replacement_requirement_id", "superseded_by_requirement_id"):
                successor = int(row.get(field) or 0)
                if successor and successor not in indexed:
                    pending.add(successor)
    return list(indexed.values())


def head_owes_work(conn, head: Mapping[str, Any]) -> bool:
    """Only failed or system-discharged heads permit automatic correction."""
    if any(
        head.get(field) and head.get(source) in {"operator", "agent"}
        for field, source in (
            ("waived_at", "waiver_source"),
            ("retracted_at", "retraction_source"),
        )
    ):
        return False
    verdict = determinate_verdict(conn, int(head["id"]))
    return verdict != "pass" and (
        verdict == "fail"
        or bool(head.get("waived_at"))
        or bool(head.get("retracted_at"))
    )


def carried_by_declared_replacement(conn, rows):
    """A foreign head carries this plan even when that head failed."""
    own = {int(row["id"]) for row in rows}
    return any(
        int(head["id"]) not in own
        for head in lineage_heads(connected_rows(conn, rows), rows)
    )


def rows_by_case(
    conn,
    *,
    run_id,
    stage_name,
    member_item_id,
    plan_id,
    group_id="",
):
    """Resolve each plan's case/baseline roots across its whole subject."""
    rows = query_rows(
        conn,
        "SELECT * FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND COALESCE(deployment_member_item_id,0)=%s "
        "AND COALESCE(execution_target_json::jsonb #>> '{deployment,shared_plan,group_id}', '')=%s ORDER BY id",
        (run_id, stage_name, member_item_id or 0, group_id),
    )
    seeds = {}
    for row in rows:
        if int(row.get("plan_id") or 0) == int(plan_id) and _included(row):
            key = (base_case_key(row["plan_case_key"]), row["host_baseline"])
            seeds.setdefault(key, []).append(row)
    return {key: lineage_heads(rows, roots) for key, roots in seeds.items()}


def predecessors_at_head(conn, requirement_id):
    """Return unsettled ancestors only when the named row is the lineage head."""
    seed = query_rows(
        conn, "SELECT * FROM qa_requirements WHERE id=%s", (requirement_id,)
    )
    rows = connected_rows(conn, seed)
    heads = lineage_heads(rows, seed)
    if not heads or int(heads[0]["id"]) != requirement_id:
        return []
    return [
        row
        for row in rows
        if int(row["id"]) != requirement_id
        and not any(
            row.get(field)
            for field in ("superseded_by_requirement_id", "waived_at", "retracted_at")
        )
    ]


def needs_corrected_row(conn, case, heads):
    """New cases or changed owed heads need a row; answered heads stand."""
    from yoke_core.domain.qa_deployment_case_content_refresh import (
        case_content_digest,
        plan_case_content_digest,
    )

    digest = plan_case_content_digest(conn, case)
    return not heads or any(
        head_owes_work(conn, head) and case_content_digest(head) != digest
        for head in heads
    )
