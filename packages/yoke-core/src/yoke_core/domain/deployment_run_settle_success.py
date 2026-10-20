"""Mark a settled run succeeded, reading before its row lock and writing under it.

Once every member has closed, success stamps the run, attributes the
delivery to every done member and records the run's carried work. The
attribution asks one question per member and carried work compares commits
on the repository host, so both are read here first, with no lock held. The
writer then locks the run row, re-reads one digest of every fact those reads
depended on, and writes. A digest that moved means a change committed in
between; the reads are repeated under the lock, so the change is honoured.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.delivery_evidence_ladder import SOURCE_MEMBERSHIP
from yoke_core.domain.gate_satisfier_ladder_catalog import OBLIGATION_DELIVERY_EVIDENCE

UNATTRIBUTED_REFUSAL = (
    "completion_delivery_unattributed: completed member has no recorded "
    "project source or registered environment; repair the run and retry success"
)


def _digest(select: str, order: str) -> str:
    return (
        f"(SELECT md5(COALESCE(string_agg(t::text,'|' ORDER BY {order}),'')) "
        f"FROM ({select}) t)"
    )


#: The run row, its members and their status, every environment an
#: attribution can name, and the preceding release carried work compares
#: against. One statement, whatever the run's size.
_SUCCESS_DIGEST = "SELECT md5(concat_ws(',',{}))".format(
    ",".join(
        (
            _digest(
                "SELECT id,project_id,target_environment_id,release_lineage,"
                "bound_sources,carried_work,status,settling_at "
                "FROM deployment_runs WHERE id=%(run)s",
                "t.id",
            ),
            _digest(
                "SELECT m.item_id,i.status,i.project_id FROM deployment_run_items m "
                "JOIN items i ON i.id=m.item_id WHERE m.run_id=%(run)s",
                "t.item_id",
            ),
            _digest(
                "SELECT e.id,e.project_id,e.name FROM environments e "
                "WHERE e.project_id IN (SELECT i.project_id FROM items i "
                "JOIN deployment_run_items m ON m.item_id=i.id WHERE m.run_id=%(run)s) "
                "OR e.id=(SELECT target_environment_id FROM deployment_runs "
                "WHERE id=%(run)s)",
                "t.id",
            ),
            _digest(
                "SELECT p.id,p.release_lineage,p.bound_sources FROM deployment_runs p "
                "JOIN deployment_runs dr ON dr.id=%(run)s "
                "WHERE p.project_id=dr.project_id AND p.status='succeeded' "
                "AND p.id<>dr.id "
                "AND p.target_environment_id IS NOT DISTINCT FROM dr.target_environment_id "
                "ORDER BY p.completed_at DESC NULLS LAST,p.created_at DESC,p.id DESC "
                "LIMIT 1",
                "t.id",
            ),
        )
    )
)


def success_digest(conn: Any, run_id: str) -> str:
    """The digest of every fact :func:`read_success` depended on."""
    return str(conn.execute(_SUCCESS_DIGEST, {"run": str(run_id)}).fetchone()[0])


@dataclass
class SuccessRead:
    """What success writes, read before the run row lock."""

    digest: str
    # Each done member's delivery attribution; ``None`` names one that has none.
    attributions: dict[int, Optional[dict[str, Any]]]
    # The derived answer to record, or ``None`` when the run already holds one.
    carried_work: Optional[dict[str, Any]]
    # Why the run's recorded answer cannot stand, raised where it was before.
    coverage_refusal: Optional[ValueError] = None

    def holds(self, conn: Any, run_id: str) -> bool:
        """Whether the same facts, read again now, give the same digest."""
        return success_digest(conn, run_id) == self.digest


def _attributions(conn: Any, run_id: str) -> dict[int, Optional[dict[str, Any]]]:
    """Every done member's attribution to this run's target, in one read."""
    from yoke_core.domain.deployment_run_project_sources import recorded_source_sha

    rows = conn.execute(
        "SELECT i.id AS item_id,dr.id,dr.project_id,dr.release_lineage,"
        "dr.bound_sources,e.id AS environment_id,e.name AS environment,"
        "i.project_id AS item_project_id FROM deployment_run_items m "
        "JOIN items i ON i.id=m.item_id JOIN deployment_runs dr ON dr.id=m.run_id "
        "LEFT JOIN environments target ON target.id=dr.target_environment_id "
        "AND target.project_id=dr.project_id "
        "LEFT JOIN environments e ON e.project_id=i.project_id AND e.name=target.name "
        "WHERE m.run_id=%s AND i.status='done' ORDER BY i.id",
        (run_id,),
    ).fetchall()
    attributions: dict[int, Optional[dict[str, Any]]] = {}
    for row in rows:
        data = dict(row)
        item_id = int(data["item_id"])
        candidate = recorded_source_sha(data, int(data["item_project_id"]))
        attributions[item_id] = (
            {
                "item_id": item_id,
                "project_id": int(data["item_project_id"]),
                "run_project_id": int(data["project_id"]),
                "run_id": run_id,
                "member_item_id": item_id,
                "environment_id": int(data["environment_id"]),
                "environment": str(data["environment"]),
                "candidate": candidate,
                "source": SOURCE_MEMBERSHIP,
            }
            if candidate and data["environment_id"] is not None
            else None
        )
    return attributions


def read_success(conn: Any, run_id: str) -> SuccessRead:
    """Read the attributions and carried work success writes, unlocked."""
    from yoke_core.domain.deployment_run_carried_work import (
        derive_carried_work_safely,
        parse_carried_work,
        require_bound_project_coverage,
    )

    digest = success_digest(conn, run_id)
    attributions = _attributions(conn, run_id)
    row = conn.execute(
        "SELECT carried_work,bound_sources FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    existing = parse_carried_work(row["carried_work"])
    read = SuccessRead(digest, attributions, None)
    if existing is None:
        read.carried_work = derive_carried_work_safely(conn, run_id)
    else:
        try:
            require_bound_project_coverage(run_id, existing, row["bound_sources"])
        except ValueError as exc:
            read.coverage_refusal = exc
    return read


def _store_attributions(conn: Any, entries: list[dict[str, Any]]) -> None:
    """Merge every member's attribution into its delivery facts, as one set."""
    from yoke_core.domain.completed_item_delivery import COMPLETED_DELIVERIES, _facts

    if not entries:
        return
    ids = sorted(int(entry["item_id"]) for entry in entries)
    stored = {
        int(row["item_id"]): _facts(row["facts"])
        for row in conn.execute(
            "SELECT item_id,facts FROM item_gate_satisfactions "
            "WHERE item_id=ANY(%s) AND obligation=%s ORDER BY item_id FOR UPDATE",
            (ids, OBLIGATION_DELIVERY_EVIDENCE),
        ).fetchall()
    }
    updates: dict[int, str] = {}
    inserts: dict[int, str] = {}
    for entry in entries:
        item_id = int(entry["item_id"])
        facts = stored.get(item_id, {})
        prior = facts.get(COMPLETED_DELIVERIES, [])
        by_identity = {
            (e["run_id"], e["environment_id"], e["candidate"]): e
            for e in (prior if isinstance(prior, list) else []) + [entry]
        }
        facts[COMPLETED_DELIVERIES] = list(by_identity.values())
        target = updates if item_id in stored else inserts
        target[item_id] = json.dumps(facts, sort_keys=True)
    if updates:
        conn.execute(
            "UPDATE item_gate_satisfactions s SET facts=v.facts "
            "FROM unnest(%s::integer[],%s::text[]) AS v(item_id,facts) "
            "WHERE s.item_id=v.item_id AND s.obligation=%s",
            (list(updates), list(updates.values()), OBLIGATION_DELIVERY_EVIDENCE),
        )
    if inserts:
        conn.execute(
            "INSERT INTO item_gate_satisfactions "
            "(item_id,obligation,rung_id,target_status,detail,facts,recorded_at) "
            "SELECT v.item_id,%s,'deployment_run_succeeded','done',%s,v.facts,%s "
            "FROM unnest(%s::integer[],%s::text[]) AS v(item_id,facts)",
            (
                OBLIGATION_DELIVERY_EVIDENCE,
                "Delivery attribution committed with item completion",
                instant_parameter(conn, utc_now()),
                list(inserts),
                list(inserts.values()),
            ),
        )


def _record_attributions(
    conn: Any, attributions: dict[int, Optional[dict[str, Any]]]
) -> None:
    if any(entry is None for entry in attributions.values()):
        raise ValueError(UNATTRIBUTED_REFUSAL)
    _store_attributions(conn, [e for e in attributions.values() if e])


def record_run_deliveries_on(conn: Any, run_id: str) -> None:
    """Attribute this run's delivery to every done member, as one set.

    The batched form of ``record_completed_run_delivery`` for a caller that
    already holds the run row and has stamped it succeeded: three statements
    whatever the number of members.
    """
    _record_attributions(conn, _attributions(conn, run_id))


def succeed_run_on(conn: Any, run_id: str, read: SuccessRead) -> None:
    """Lock the run, re-check *read*, and write success in the open transaction.

    The caller withdraws the run's waits and commits. A digest that moved
    since *read* repeats the read under the lock before anything is written.
    """
    from yoke_core.domain.deployment_runs_lock import lock_run
    from yoke_core.domain.environment_delivery_record import stamp_run_environment
    from yoke_core.domain.json_helper import dumps_compact

    lock_run(conn, run_id)
    if not read.holds(conn, run_id):
        read = read_success(conn, run_id)
    completed_at = utc_now()
    conn.execute(
        "UPDATE deployment_runs SET status=%s, completed_at=%s WHERE id=%s",
        ("succeeded", instant_parameter(conn, completed_at), run_id),
    )
    stamp_run_environment(conn, run_id, when=completed_at)
    _record_attributions(conn, read.attributions)
    if read.coverage_refusal is not None:
        raise read.coverage_refusal
    if read.carried_work is not None:
        conn.execute(
            "UPDATE deployment_runs SET carried_work=%s WHERE id=%s",
            (dumps_compact(read.carried_work), run_id),
        )


__all__ = [
    "SuccessRead",
    "read_success",
    "record_run_deliveries_on",
    "succeed_run_on",
    "success_digest",
]
