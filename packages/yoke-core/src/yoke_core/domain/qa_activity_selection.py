"""How an activity read is narrowed to its subjects and bounded.

Reading a set of items' QA as one recency page is a defect rather than a
page: the busiest subject fills the cap and every other requested subject
reads back as having nothing. A caller drawing known run groups therefore
gets a read bounded per subject per deployment run, restricted to those
groups. A caller naming no run groups asked for at most ``limit`` rows, and
gets that many, newest first. Either way the read says what it cut short.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Optional

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_latest_execution import latest_execution_id_sql


def item_filter(
    marker: str,
    params: list[Any],
    item_ids: Optional[Iterable[int]],
) -> str:
    """Narrow to the QA a set of items owns, however each row is attached.

    An item-attached requirement names its item directly and records no
    deployment run; a run's per-member check names the member instead. A
    caller asking for one item's evidence means both, so neither shape is
    silently missing from what it reads back.

    Asking for no items is not the same as asking for every item: an empty
    selection matches nothing rather than widening to the whole project.
    """
    if item_ids is None:
        return ""
    wanted = sorted({int(value) for value in item_ids})
    if not wanted:
        return " AND 1 = 0"
    markers = ", ".join(marker for _ in wanted)
    params.extend(wanted)
    params.extend(wanted)
    return (
        f" AND (q.item_id IN ({markers}) OR q.deployment_member_item_id IN ({markers}))"
    )


def run_group_filter(
    marker: str,
    params: list[Any],
    run_ids: Optional[Iterable[str]],
) -> str:
    """Keep the run groups a caller is drawing, plus run-less item checks.

    Without this an item's rows arrive for every release it ever took part
    in, so the answer grows with an item's lifetime rather than with what is
    on screen. The run-less group always travels: it is the item's own QA,
    which belongs to no release and is what a card labels as such.
    """
    if run_ids is None:
        return ""
    wanted = sorted({str(value) for value in run_ids if str(value or "").strip()})
    if not wanted:
        return " AND q.deployment_run_id IS NULL"
    markers = ", ".join(marker for _ in wanted)
    params.extend(wanted)
    return f" AND (q.deployment_run_id IS NULL OR q.deployment_run_id IN ({markers}))"


HAPPENED_AT = "COALESCE(r.completed_at, r.created_at, q.created_at)"

ACTIVITY_COLUMNS = (
    "q.id AS requirement_id, q.plan_id, q.plan_case_key, "
    "q.deployment_run_id, q.standalone_execution_id, q.deployment_stage, q.item_id, "
    "q.deployment_member_item_id, q.qa_kind, q.qa_phase, "
    "q.execution_target_json, "
    "q.waived_at, q.waiver_rationale, q.instructions, "
    "q.retracted_at, q.retraction_rationale, q.retraction_source, "
    "q.superseded_by_requirement_id, q.superseded_at, "
    "q.replacement_requirement_id, "
    "q.host_baseline, p.slug AS plan, pr.slug AS project, "
    "q.method_id, q.method_name, m.proof_kind, r.id AS run_id, "
    "r.performed_by, "
    "r.verdict, r.verdict_reason, r.case_outcome, r.execution_status, "
    "r.capture_degraded_reason, "
    "r.raw_result, "
    f"{HAPPENED_AT} AS happened_at"
)

#: Which requirements an activity read is about, and which it leaves out.
#: A case is executable when it names a registered method — that is true of
#: every plan-backed case and equally true of one attached straight to an
#: item or a deployment run without a plan. Requiring a plan instead made a
#: storage detail decide visibility: an item's own ad hoc verification, and
#: every standalone run case, recorded passing runs and screenshots that no
#: surface could read back. Recorded post-deploy facts — no-obligation and
#: a waiver-backed "not required" — also belong here: they never execute,
#: but they are the only durable distinction from silence. What stays out is
#: method-less run machinery (stage acceptance) and acceptance-criterion
#: markers that never execute and never record an answer.
EXECUTABLE_REQUIREMENT = (
    "(q.plan_id IS NOT NULL OR q.method_id IS NOT NULL "
    "OR q.qa_kind IN ('post_deploy_no_obligation', 'post_deploy_not_required'))"
)

#: Which project a requirement belongs to, however it is attached. A
#: deployment member owns its stage cases; otherwise a plan-backed row
#: inherits its plan's project, and a planless row takes its item or run.
#: projects join stays inner, so a row whose project cannot be resolved this
#: way is readable by nobody rather than by every tenant.
def project_of_requirement(*, member="mi", plan="p", item="si", run="dr") -> str:
    """SQL project precedence shared by requirement execution and evidence reads."""
    return f"COALESCE({member}.project_id,{plan}.project_id,{item}.project_id,{run}.project_id)"


PROJECT_OF_REQUIREMENT = project_of_requirement()

#: What a project-scoped read filters on. It is the resolved project above,
#: read off the joined row, so plan-backed and planless rows are scoped by
#: one rule rather than by whichever table happens to carry the id.
PROJECT_FILTER_COLUMN = "pr.id"

ACTIVITY_SOURCE = (
    "FROM qa_requirements q "
    "LEFT JOIN qa_plans p ON p.id=q.plan_id "
    "LEFT JOIN items si ON si.id=COALESCE(q.item_id, q.epic_id) "
    "LEFT JOIN items mi ON mi.id=q.deployment_member_item_id "
    "LEFT JOIN deployment_runs dr ON dr.id=q.deployment_run_id "
    f"JOIN projects pr ON pr.id={PROJECT_OF_REQUIREMENT} "
    "LEFT JOIN qa_methods m ON m.id=q.method_id "
    "LEFT JOIN qa_runs r ON r.id=("
    f"{latest_execution_id_sql('q.id')})"
)

#: Which item a row belongs to. An item-attached requirement names its item;
#: a run's per-member check names the member instead. Readers group by the
#: same rule, so what the query bounds and what a caller shows agree.
SUBJECT = "COALESCE(q.item_id, q.deployment_member_item_id)"

#: What a run-group read bounds: each item's checks WITHIN each deployment
#: run they were recorded against, with the item's own run-less checks as
#: their own group. Bounding an item as a whole would let its busiest release
#: cut off the very rows another release's card needs — the read would drop
#: them before the caller could filter to the run it is drawing, so a card
#: would report nothing for an item that has evidence for exactly that run.
SUBJECT_GROUP = f"{SUBJECT}, q.deployment_run_id"


def subject_of(row: Any) -> Optional[int]:
    value = row["item_id"]
    if value is None:
        value = row["deployment_member_item_id"]
    return None if value is None else int(value)


def activity_query(marker: str, where: str, *, per_run_group: bool) -> str:
    """The recency page, or the per-subject-per-run bounded selection."""
    if not per_run_group:
        return (
            f"SELECT {ACTIVITY_COLUMNS} {ACTIVITY_SOURCE} {where} "
            f"ORDER BY happened_at DESC, q.id DESC LIMIT {marker}"
        )
    return (
        f"SELECT * FROM (SELECT {ACTIVITY_COLUMNS}, ROW_NUMBER() OVER ("
        f"PARTITION BY {SUBJECT_GROUP} "
        f"ORDER BY {HAPPENED_AT} DESC, q.id DESC"
        f") AS item_rank {ACTIVITY_SOURCE} {where}) ranked "
        f"WHERE item_rank<={marker} "
        "ORDER BY happened_at DESC, requirement_id DESC"
    )


def bound_groups(
    rows: list[Any],
    bounded: int,
) -> tuple[list[Any], dict[str, Any]]:
    """Drop each group's probe row, and name the groups that carried one.

    Truncation is reported per group because that is the unit that was
    bounded: a caller drawing one release must be able to say what it cut
    short there, rather than claim a count across every group it happens to
    be showing.
    """
    kept: list[Any] = []
    counts: Counter = Counter()
    truncated: set[tuple[int, Optional[str]]] = set()
    for row in rows:
        subject = subject_of(row)
        run = row["deployment_run_id"] or None
        group = (subject, run)
        counts[group] += 1
        if counts[group] > bounded:
            if subject is not None:
                truncated.add((subject, run))
            continue
        kept.append(row)
    return kept, {
        "per_group_limit": bounded,
        "truncated_groups": [
            {"item_id": item_id, "deployment_run_id": run}
            for item_id, run in sorted(
                truncated, key=lambda entry: (entry[0], entry[1] or "")
            )
        ],
    }


def bound_total(
    conn: Any,
    rows: list[Any],
    bounded: int,
    where: str,
    params: list[Any],
    offset: int = 0,
) -> tuple[list[Any], dict[str, Any]]:
    """Keep the newest ``bounded`` rows, and count what matched when cut.

    The probe row past the cap is what proves a cut; only then is the full
    match counted, so a reader knows how far to narrow or raise the limit.
    """
    truncated = len(rows) > bounded
    total = len(rows)
    if truncated or offset:
        counted = query_rows(
            conn, f"SELECT COUNT(*) AS total {ACTIVITY_SOURCE} {where}", tuple(params)
        )
        total = int(counted[0]["total"])
    return rows[:bounded], {"limit": bounded, "total": total, "truncated": truncated}


def select_activity(
    conn: Any,
    marker: str,
    where: str,
    params: list[Any],
    *,
    bounded: int,
    item_scoped: bool,
    per_run_group: bool,
    offset: int = 0,
) -> tuple[list[Any], Optional[dict[str, Any]]]:
    """Run the bounded read, and say how an item-scoped one was bounded.

    Only a caller naming the run groups it draws gets the per-run bound: it
    already sized the answer by what is on screen. Without them every run an
    item ever took part in is a group, so a per-run bound would grow with the
    item's lifetime instead of honouring the limit the caller asked for.
    """
    if per_run_group and offset:
        raise ValueError(
            "activity_group_offset_unsupported: omit --offset for per-run group reads"
        )
    probe = bounded + 1 if item_scoped else bounded
    rows = query_rows(
        conn,
        activity_query(marker, where, per_run_group=per_run_group)
        + (f" OFFSET {marker}" if not per_run_group else ""),
        (*params, probe, offset) if not per_run_group else (*params, probe),
    )
    if not item_scoped:
        return rows, None
    if per_run_group:
        return bound_groups(rows, bounded)
    return bound_total(conn, rows, bounded, where, params, offset=offset)


__all__ = [
    "ACTIVITY_COLUMNS",
    "ACTIVITY_SOURCE",
    "EXECUTABLE_REQUIREMENT",
    "HAPPENED_AT",
    "PROJECT_FILTER_COLUMN",
    "PROJECT_OF_REQUIREMENT",
    "SUBJECT",
    "SUBJECT_GROUP",
    "activity_query",
    "bound_groups",
    "bound_total",
    "item_filter",
    "run_group_filter",
    "select_activity",
    "subject_of",
]
