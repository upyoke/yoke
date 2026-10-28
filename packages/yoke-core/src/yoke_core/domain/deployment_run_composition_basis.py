"""One digest of what a run's composition reads, taken before and under its lock.

Starting a run, enrolling its carried members and refreshing its bound
sources each ask questions whose cost grows with the run: one answer per
member or per carried landing. Those reads run before the ``deployment_runs``
row lock. The caller takes this basis before the reads and again under the
lock; an equal digest proves no committed change landed in between, so the
lock covers a constant re-check and the writes. A changed digest sends the
caller back to its locked reads, which is how a racing writer is honoured.

The digest extends :func:`run_qa_fingerprint` with the composition's own
inputs: the run's source, carried-work and removal columns and its flow, the
membership rows, every item the reads judged (members, the caller's carried
set, and the landed nonterminal items of each carried project), the runs
already holding those items, their dependencies, the members' QA requirement
and plan rows, and the preceding succeeded release. Two statements, whatever
the run's size.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from yoke_core.domain.conflict_survey_declared_paths import TERMINAL_STATUSES
from yoke_core.domain.deployment_run_qa_fingerprint import run_qa_fingerprint
from yoke_core.domain.schema_common import _get_columns, _table_exists


def _digest(select: str, order: str) -> str:
    return (
        f"(SELECT md5(COALESCE(string_agg(t::text,'|' ORDER BY {order}),'')) "
        f"FROM ({select}) t)"
    )


#: Items a composition read judges: the named ones, plus every landed,
#: nonterminal item of a carried project, which is the custody walk's input.
_JUDGED_ITEMS = (
    "SELECT id FROM items WHERE id=ANY(%(items)s) OR (project_id=ANY(%(projects)s) "
    "AND status<>ALL(%(terminal)s) AND ({landed}))"
)
#: Columns the digest reads when the schema has them. A release may start
#: before a later column converges, so each is named only once it exists.
_RUN_COLUMNS = (
    "project_id",
    "flow",
    "target_tier",
    "target_environment_id",
    "release_lineage",
    "status",
    "carried_work",
    "bound_sources",
    "candidate_containment",
    "composition_resolution",
    "composition_frozen_at",
    "membership_removals",
)
_ITEM_COLUMNS = (
    "id",
    "status",
    "project_id",
    "workflow_id",
    "workflow_version_id",
    "deployment_flow",
    "merged_at",
    "merge_queue_landed_at",
)
_LANDING_COLUMNS = ("merged_at", "merge_queue_landed_at")
_MEMBER_PLANS = (
    "SELECT plan_id FROM qa_plan_item_attachments WHERE item_id=ANY(%(items)s) "
    "UNION SELECT plan_id FROM qa_requirements WHERE item_id=ANY(%(items)s) "
    "AND plan_id IS NOT NULL"
)


def _parts(run_columns: str, item_columns: str, landed: str) -> tuple[str, ...]:
    judged = _JUDGED_ITEMS.format(landed=landed)
    return (
        _digest(
            f"SELECT {run_columns},df AS flow_row "
            "FROM deployment_runs dr JOIN deployment_flows df ON df.id=dr.flow "
            "WHERE dr.id=%(run)s",
            "t.project_id",
        ),
        _digest(
            "SELECT item_id,delivery_intent,requirement_selection "
            "FROM deployment_run_items WHERE run_id=%(run)s",
            "t.item_id",
        ),
        _digest(
            f"SELECT {item_columns} FROM items WHERE id IN ({judged})",
            "t.id",
        ),
        _digest(
            "SELECT m.run_id,m.item_id,r.status FROM deployment_run_items m "
            "JOIN deployment_runs r ON r.id=m.run_id "
            f"WHERE m.run_id<>%(run)s AND m.item_id IN ({judged})",
            "t.run_id,t.item_id",
        ),
        _digest(
            "SELECT d.*,b.status AS blocker_status FROM item_dependencies d "
            "LEFT JOIN items b ON b.id=d.blocking_item_id "
            "WHERE d.dependent_item_id=ANY(%(items)s)",
            "t.id",
        ),
        _digest(
            "SELECT r.* FROM qa_requirements r WHERE r.item_id=ANY(%(items)s)",
            "t.id",
        ),
        _digest(
            f"SELECT p.* FROM qa_plans p WHERE p.id IN ({_MEMBER_PLANS})",
            "t.id",
        ),
        _digest(
            f"SELECT c.* FROM qa_plan_cases c WHERE c.plan_id IN ({_MEMBER_PLANS})",
            "t.id",
        ),
        _digest(
            "SELECT p.id,p.release_lineage,p.bound_sources FROM deployment_runs p "
            "JOIN deployment_runs dr ON dr.id=%(run)s "
            "WHERE p.project_id=dr.project_id AND p.status='succeeded' "
            "AND p.id<>dr.id "
            "AND p.target_environment_id IS NOT DISTINCT FROM dr.target_environment_id "
            "ORDER BY p.completed_at DESC NULLS LAST,p.created_at DESC,p.id DESC LIMIT 1",
            "t.id",
        ),
    )


def _composition_digest(
    conn: Any, run_id: str, item_ids: tuple[int, ...], project_ids: tuple[int, ...]
) -> str:
    run_present = set(_get_columns(conn, "deployment_runs"))
    item_present = set(_get_columns(conn, "items"))
    landed = [c for c in _LANDING_COLUMNS if c in item_present]
    parts = _parts(
        ",".join(f"dr.{c}" for c in _RUN_COLUMNS if c in run_present),
        ",".join(c for c in _ITEM_COLUMNS if c in item_present),
        " OR ".join(f"{c} IS NOT NULL" for c in landed) or "FALSE",
    )
    row = conn.execute(
        f"SELECT md5(concat_ws(',',{','.join(parts)}))",
        {
            "run": str(run_id),
            "items": list(item_ids),
            "projects": list(project_ids),
            "terminal": sorted(TERMINAL_STATUSES),
        },
    ).fetchone()
    return f"{run_qa_fingerprint(conn, run_id)}:{row[0]}"


@dataclass(frozen=True)
class CompositionBasis:
    """The digest a composition's unlocked reads started from."""

    run_id: str
    item_ids: tuple[int, ...]
    project_ids: tuple[int, ...]
    digest: str

    def unchanged(self, conn: Any) -> bool:
        """Whether the same facts, read again now, still give the same digest."""
        return (
            _composition_digest(conn, self.run_id, self.item_ids, self.project_ids)
            == self.digest
        )


#: Every table the digest reads. A schema missing one cannot prove its reads
#: current, so its caller keeps every read under the lock.
_DIGEST_TABLES = (
    "item_dependencies",
    "qa_requirements",
    "qa_plans",
    "qa_plan_cases",
    "qa_plan_item_attachments",
    "qa_runs",
    "deployment_stage_receipts",
)


#: Columns :func:`run_qa_fingerprint` names unconditionally.
_FINGERPRINT_COLUMNS = {
    "deployment_runs": ("current_stage", "settling_at", "requirement_snapshot"),
    "deployment_run_items": ("requirement_snapshot",),
    "qa_requirements": (
        "deployment_stage",
        "deployment_member_item_id",
        "execution_target_digest",
        "superseded_by_requirement_id",
        "replacement_requirement_id",
    ),
}


def read_composition_basis(
    conn: Any, run_id: str, *, item_ids: Iterable[int], project_ids: Iterable[int]
) -> CompositionBasis | None:
    """Take the basis before the reads it guards; see :class:`CompositionBasis`.

    ``None`` when this schema cannot answer the digest yet.
    """
    if not all(_table_exists(conn, table) for table in _DIGEST_TABLES):
        return None
    for table, columns in _FINGERPRINT_COLUMNS.items():
        if not set(columns) <= set(_get_columns(conn, table)):
            return None
    items = tuple(sorted({int(value) for value in item_ids}))
    projects = tuple(sorted({int(value) for value in project_ids}))
    return CompositionBasis(
        str(run_id), items, projects, _composition_digest(conn, run_id, items, projects)
    )


def lock_snapshot_rows(
    conn: Any, requirement_ids: Iterable[int], plan_ids: Iterable[int] = ()
) -> None:
    """Hold the requirement and plan rows an unlocked snapshot read, in id order.

    Taken under the run lock and before the basis re-check, the same order the
    locked snapshot read takes them, so the rows the snapshot froze stay as
    read until the caller's transaction ends.
    """
    requirements = sorted({int(value) for value in requirement_ids})
    plans = sorted({int(value) for value in plan_ids})
    if requirements:
        conn.execute(
            "SELECT id FROM qa_requirements WHERE id=ANY(%s) ORDER BY id FOR UPDATE",
            (requirements,),
        )
    if plans:
        conn.execute(
            "SELECT id FROM qa_plans WHERE id=ANY(%s) ORDER BY id FOR UPDATE",
            (plans,),
        )


__all__ = ["CompositionBasis", "lock_snapshot_rows", "read_composition_basis"]
