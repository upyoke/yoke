"""Retire a post-deploy item source in favor of a corrected item requirement.

A ``post_deploy`` item requirement never executes itself: each release
admits a frozen copy of it onto the run, and only that copy is graded. When
the copy fails because the source was worded wrong, the run-local fix is a
corrected run case that supersedes the copy. That settles this run and
nothing else -- the source still carries the broken body, so the next
release admits it again.

Retirement is the step that makes the correction stick. The operator
records the corrected body as a new item requirement for the same item,
transition, phase and target, then supersedes the source with it. Neither
item row has a verdict to show (post-deploy sources are never run), so the
proof is the run's: at least one admitted copy of the source must already be
superseded by a run case that passed. That passing case stays the answer
for its run -- :func:`admitted_source_lineage` lets the corrected
requirement read the retired source's copies on a run that admitted the
source -- and later releases admit only the corrected body, because
admission skips a superseded source. Nothing rewrites the source row; the
supersession link is the whole record.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_identity_clause,
    admitted_source_requirement_id,
)
from yoke_core.domain.qa_obligation_settlement import (
    obligation_settled,
    requirement_retracted_at_select,
)

#: Said when the discharged row is an admitted copy whose source row is still
#: outstanding. Supersession is run-local by design, so this is the one moment
#: the operator holds the corrected body AND the system knows which row the
#: next release will copy it from.
NEXT_ADMISSION_NOTICE = (
    "requirement {copy_id} was admitted from item requirement {source_id}, "
    "which this supersession does not touch, so the next release admits a "
    "fresh copy of the same body. Retire the source: record the corrected "
    "body as a new item requirement (yoke qa requirement add --item "
    "<item ref> --method-id {method_id} --qa-phase post_deploy "
    "--workflow-transition {transition} --target-env {target_env} with the "
    "corrected --instructions, --expected-outcome and --method-config), then "
    "yoke qa requirement supersede --requirement-id {source_id} "
    "--superseded-by-requirement-id <corrected-item-requirement-id> "
    "--rationale '<why the corrected body answers it>'"
)

#: Refused when no admitted copy of the source was answered by a passing run
#: case: neither item row ever executes, so nothing else proves the new body.
SOURCE_RETIREMENT_REFUSAL = (
    "requirement {source_id} is a post_deploy item source: neither it nor a "
    "corrected item requirement ever executes, so the proof that the "
    "corrected body is right comes from a run. Correct one of its admitted "
    "copies first -- materialize the corrected case with --replaces "
    "CASE_KEY=<failed copy id> on that run's stage and record its passing "
    "verdict -- then re-run this supersede."
)

_LINEAGE_COLUMNS = "id,item_id,plan_id,plan_case_key"


def is_source_retirement(broken: Mapping[str, Any]) -> bool:
    """Whether superseding *broken* retires a post-deploy item source."""
    return (
        not broken.get("deployment_run_id")
        and broken.get("item_id") is not None
        and str(broken.get("qa_phase") or "") == "post_deploy"
    )


def _latest_verdict(conn: Any, requirement_id: int) -> str:
    row = query_one(
        conn,
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (int(requirement_id),),
    )
    return str(row["verdict"] or "") if row is not None else ""


def passing_run_replacement(conn: Any, source: Mapping[str, Any]) -> int | None:
    """The passing run case that superseded an admitted copy of *source*."""
    identity, params = admitted_requirement_identity_clause(source)
    copies = query_rows(
        conn,
        "SELECT superseded_by_requirement_id FROM qa_requirements "
        f"WHERE deployment_run_id IS NOT NULL AND deployment_member_item_id=%s "
        f"AND superseded_by_requirement_id IS NOT NULL AND {identity} ORDER BY id",
        (int(source["item_id"]), *params),
    )
    for copy in copies:
        replacement_id = int(copy["superseded_by_requirement_id"])
        if _latest_verdict(conn, replacement_id) == "pass":
            return replacement_id
    return None


def admitted_source_lineage(
    conn: Any, source: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """*source* plus every item source retired in its favor, transitively.

    A run that admitted a retired source answers the corrected requirement
    through those copies; a later run admits only the corrected body.
    """
    lineage = [dict(source)]
    seen = {int(source["id"])}
    position = 0
    while position < len(lineage):
        successor = lineage[position]
        position += 1
        for row in query_rows(
            conn,
            f"SELECT {_LINEAGE_COLUMNS} FROM qa_requirements "
            "WHERE deployment_run_id IS NULL AND item_id=%s "
            "AND superseded_by_requirement_id=%s ORDER BY id",
            (int(source["item_id"]), int(successor["id"])),
        ):
            if int(row["id"]) not in seen:
                seen.add(int(row["id"]))
                lineage.append(dict(row))
    return lineage


def lineage_identity_clause(
    conn: Any, source: Mapping[str, Any], *, marker: str = "%s"
) -> tuple[str, tuple[Any, ...]]:
    """Admitted-copy identity for *source* and every source it retired."""
    clauses: list[str] = []
    params: list[Any] = []
    for row in admitted_source_lineage(conn, source):
        clause, row_params = admitted_requirement_identity_clause(row, marker=marker)
        clauses.append(f"({clause})")
        params.extend(row_params)
    return "(" + " OR ".join(clauses) + ")", tuple(params)


def admitted_source_correction(conn: Any, broken: Mapping[str, Any]) -> dict[str, Any]:
    """Name the source row this discharged copy was frozen from, if any.

    Returns empty when there is nothing true to say: a run-bound case that is
    not an admitted copy names no upstream, and neither does one whose source
    row has been deleted or is itself already settled -- a settled row is not
    outstanding, so no future release admits it and there is nothing left to
    correct. The notice is never invented to fill the field.
    """
    source_id = admitted_source_requirement_id(broken.get("plan_case_key"))
    if source_id is None:
        return {}
    source = query_one(
        conn,
        "SELECT id,method_id,workflow_transition_id,target_env,waived_at,"
        f"superseded_by_requirement_id,{requirement_retracted_at_select(conn)} "
        "FROM qa_requirements WHERE id=%s",
        (int(source_id),),
    )
    if source is None or obligation_settled(dict(source)):
        return {}
    return {
        "admitted_from_requirement_id": int(source_id),
        "next_admission_notice": NEXT_ADMISSION_NOTICE.format(
            copy_id=int(broken["id"]),
            source_id=int(source_id),
            method_id=source["method_id"] or "<method>",
            transition=source["workflow_transition_id"] or "<transition>",
            target_env=source["target_env"] or "<environment>",
        ),
    }


__all__ = [
    "NEXT_ADMISSION_NOTICE",
    "SOURCE_RETIREMENT_REFUSAL",
    "admitted_source_correction",
    "admitted_source_lineage",
    "is_source_retirement",
    "lineage_identity_clause",
    "passing_run_replacement",
]
