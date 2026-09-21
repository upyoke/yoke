"""How an activity read is narrowed to its subjects and bounded.

Reading a set of items' QA as one recency page is a defect rather than a
page: the busiest subject fills the cap and every other requested subject
reads back as having nothing. What this module composes instead is a read
bounded per subject per deployment run, restricted to the run groups a
caller is actually drawing, and honest about what it cut short.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Optional


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
    "q.deployment_run_id, q.deployment_stage, q.item_id, "
    "q.deployment_member_item_id, q.qa_kind, q.qa_phase, "
    "q.execution_target_json, "
    "q.waived_at, q.waiver_rationale, q.instructions, "
    "q.superseded_by_requirement_id, q.superseded_at, "
    "q.host_baseline, p.slug AS plan, pr.slug AS project, "
    "q.method_id, q.method_name, m.proof_kind, r.id AS run_id, "
    "r.performed_by, "
    "r.verdict, r.verdict_reason, r.case_outcome, r.capture_degraded_reason, "
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
#: plan-backed row inherits its plan's project; a planless row takes it from
#: the subject it names — its item, its epic, or its deployment run. The
#: projects join stays inner, so a row whose project cannot be resolved this
#: way is readable by nobody rather than by every tenant.
PROJECT_OF_REQUIREMENT = "COALESCE(p.project_id, si.project_id, dr.project_id)"

#: What a project-scoped read filters on. It is the resolved project above,
#: read off the joined row, so plan-backed and planless rows are scoped by
#: one rule rather than by whichever table happens to carry the id.
PROJECT_FILTER_COLUMN = "pr.id"

ACTIVITY_SOURCE = (
    "FROM qa_requirements q "
    "LEFT JOIN qa_plans p ON p.id=q.plan_id "
    "LEFT JOIN items si ON si.id=COALESCE(q.item_id, q.epic_id) "
    "LEFT JOIN deployment_runs dr ON dr.id=q.deployment_run_id "
    f"JOIN projects pr ON pr.id={PROJECT_OF_REQUIREMENT} "
    "LEFT JOIN qa_methods m ON m.id=q.method_id "
    "LEFT JOIN qa_runs r ON r.id=("
    "SELECT rr.id FROM qa_runs rr WHERE rr.qa_requirement_id=q.id "
    "ORDER BY rr.created_at DESC, rr.id DESC LIMIT 1)"
)

#: Which item a row belongs to. An item-attached requirement names its item;
#: a run's per-member check names the member instead. Readers group by the
#: same rule, so what the query bounds and what a caller shows agree.
SUBJECT = "COALESCE(q.item_id, q.deployment_member_item_id)"

#: What an item-scoped read bounds: each item's checks WITHIN each deployment
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


def activity_query(marker: str, where: str, *, item_scoped: bool) -> str:
    """The recency page, or the per-subject-per-run bounded selection."""
    if not item_scoped:
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
    "item_filter",
    "run_group_filter",
    "subject_of",
]
