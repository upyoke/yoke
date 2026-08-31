"""Item-scoped observations the control plane can make about one item.

Project facts answer "what shape is this project"; these answer "what
did this item actually produce". Both are read where they live — on the
server — rather than at whichever machine happens to be driving the
transition, because an https control plane hands the driving machine no
database to open and a fact resolved two different ways is a fact with
two different answers.

Carrying the ``item:`` prefix keeps that provenance visible in the
refusal narrative and in the stamped fact snapshot: a reader can tell
"the control plane looked and found no passing CI run" from "this
machine could not see a ref".
"""

from __future__ import annotations

from typing import Any, Dict

from yoke_core.domain.gate_satisfier_facts import Fact, FactVerdict
from yoke_core.domain.schema_common import _column_exists


ITEM_CI_VERDICT = "item:ci_verdict"
ITEM_DEPLOYMENT_RUN_SUCCEEDED = "item:deployment_run_succeeded"
ITEM_NO_DEPLOYMENT_TARGET = "item:no_deployment_target"


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _count(conn: Any, sql: str, params: tuple, *columns: tuple) -> int:
    """Count rows, or ``-1`` when a column the read needs is absent.

    Probes the catalog first: on Postgres a failed statement aborts the
    whole transaction, so letting a missing table or column raise here
    would make every later fact in the same registry load unanswerable
    too.
    """
    if any(not _column_exists(conn, table, column) for table, column in columns):
        return -1
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0) if row else 0


def _fact(key: str, count: int, present_detail: str, absent_detail: str) -> Fact:
    if count < 0:
        return Fact(
            key=key,
            verdict=FactVerdict.UNKNOWN,
            detail=(
                "the table backing this fact could not be read; converge "
                "the schema (a server applies pending schema on boot) and "
                "retry"
            ),
        )
    if count:
        return Fact(key=key, verdict=FactVerdict.PRESENT, value=str(count),
                    detail=present_detail.format(count=count))
    return Fact(key=key, verdict=FactVerdict.ABSENT, value="0",
                detail=absent_detail)


def _no_deployment_target(conn: Any, item_id: int) -> Fact:
    """Whether this item has anywhere to deploy other than the trunk.

    An empty ``deployment_flow``, a ``*-internal`` flow, or a registered
    flow whose ``target_tier`` is empty all mean the same thing: landing
    on the trunk IS the delivery. That is a real satisfier, and naming
    it is what stops it from reading as an obligation that evaporated.
    A flow with a real target tier makes this fact ABSENT, which is what
    keeps the merge-only rung out of reach for an item that owes a
    deployment.
    """
    if not _column_exists(conn, "items", "deployment_flow"):
        return Fact(
            key=ITEM_NO_DEPLOYMENT_TARGET,
            verdict=FactVerdict.UNKNOWN,
            detail="items.deployment_flow could not be read",
        )
    p = _p(conn)
    row = conn.execute(
        f"SELECT deployment_flow FROM items WHERE id = {p}", (item_id,)
    ).fetchone()
    flow = str((row[0] if row else "") or "").strip()
    if not flow or flow.endswith("-internal"):
        return Fact(
            key=ITEM_NO_DEPLOYMENT_TARGET,
            verdict=FactVerdict.PRESENT,
            value=flow,
            detail=(
                "the item declares no deployment flow"
                if not flow
                else f"the item's flow {flow!r} is merge-only by name"
            ),
        )
    if not _column_exists(conn, "deployment_flows", "target_tier"):
        return Fact(
            key=ITEM_NO_DEPLOYMENT_TARGET,
            verdict=FactVerdict.UNKNOWN,
            detail="deployment_flows.target_tier could not be read",
        )
    tier_row = conn.execute(
        f"SELECT target_tier FROM deployment_flows WHERE id = {p}", (flow,)
    ).fetchone()
    tier = str((tier_row[0] if tier_row else "") or "").strip()
    if tier:
        return Fact(
            key=ITEM_NO_DEPLOYMENT_TARGET,
            verdict=FactVerdict.ABSENT,
            value=flow,
            detail=(
                f"the item's flow {flow!r} targets tier {tier!r}, so merging "
                "is not by itself the delivery"
            ),
        )
    return Fact(
        key=ITEM_NO_DEPLOYMENT_TARGET,
        verdict=FactVerdict.PRESENT,
        value=flow,
        detail=f"the registered flow {flow!r} declares no target tier",
    )


def load_item_facts(conn: Any, item_id: int) -> Dict[str, Fact]:
    """Return the item-scoped facts every migrated ladder may consult."""
    p = _p(conn)
    ci = _count(
        conn,
        "SELECT COUNT(*) FROM qa_runs r "
        "JOIN qa_requirements q ON q.id = r.qa_requirement_id "
        f"WHERE q.item_id = {p} AND r.performed_by = 'ci_run' "
        "AND r.verdict = 'pass'",
        (item_id,),
        ("qa_runs", "performed_by"),
        ("qa_requirements", "item_id"),
    )
    deployed = _count(
        conn,
        "SELECT COUNT(*) FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dr.id = dri.run_id "
        f"WHERE dri.item_id = {p} AND dr.status = 'succeeded'",
        (item_id,),
        ("deployment_runs", "status"),
        ("deployment_run_items", "item_id"),
    )
    return {
        ITEM_CI_VERDICT: _fact(
            ITEM_CI_VERDICT,
            ci,
            "{count} passing CI run(s) recorded against this item",
            "no passing CI run is recorded against this item",
        ),
        ITEM_DEPLOYMENT_RUN_SUCCEEDED: _fact(
            ITEM_DEPLOYMENT_RUN_SUCCEEDED,
            deployed,
            "{count} succeeded item-bound deployment run(s)",
            "no item-bound deployment run has succeeded",
        ),
        ITEM_NO_DEPLOYMENT_TARGET: _no_deployment_target(conn, item_id),
    }


__all__ = [
    "ITEM_CI_VERDICT",
    "ITEM_DEPLOYMENT_RUN_SUCCEEDED",
    "ITEM_NO_DEPLOYMENT_TARGET",
    "load_item_facts",
]
