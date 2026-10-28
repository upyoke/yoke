"""Retire a post-deploy item source in favor of a corrected item requirement.

A ``post_deploy`` item requirement never executes itself: each release
admits a frozen copy of it onto the run, and only that copy is graded. When
the copy fails because the source was worded wrong, the run-local fix is a
corrected run case that supersedes the copy. That settles this run and
nothing else -- the source still carries the broken body, so the next
release admits it again.

Retirement is the step that makes the correction stick. The operator
records the corrected body as a new item requirement for the same item,
transition, phase and resolved environment, then supersedes the source with
it. Neither item row has a verdict to show (post-deploy sources are never
run), so the proof comes from a run, and which run depends on where the
source's copies are:

* A run the item still belongs to holds a copy. That run will grade the
  corrected requirement through the copy, so the copy must already be
  replaced or superseded by a run case whose terminal successor passed. That
  passing case stays the answer for its run -- :func:`admitted_source_lineage`
  lets the corrected requirement read the retired source's copies on a run
  that admitted the source.
* No live membership holds a copy: the item was removed from the run that
  admitted it (or that run failed or was cancelled), or no run admitted it
  yet. A failed copy left there is history that grades nothing, and no run
  can correct it any more. Retirement records the supersession and the
  corrected requirement owes its own proof: the next release carrying the
  item admits only the corrected body, and done waits for that copy.

Later releases admit only the corrected body, because admission skips a
superseded source. Nothing rewrites the source row; the supersession link
is the whole record.
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
    "--workflow-transition {transition} --target-env {target_env} naming the "
    "source snapshot destination (no matching snapshot digest is needed), with the "
    "corrected --instructions, --expected-outcome and --method-config), then "
    "yoke qa requirement supersede --requirement-id {source_id} "
    "--superseded-by-requirement-id <corrected-item-requirement-id> "
    "--rationale '<why the corrected body answers it>'"
)

#: Refused when a run the item still belongs to holds a copy of the source
#: and no copy was answered by a passing run case: that run grades the
#: corrected requirement through the copy, so the copy must be corrected first.
SOURCE_RETIREMENT_REFUSAL = (
    "source_retirement_unproven: requirement {source_id} is a post_deploy item source "
    "whose admitted copies {copy_ids} sit on runs the item still belongs to "
    "({run_ids}), and none was answered by a passing corrected case. Those runs "
    "grade the corrected requirement through the copies, so correct one first "
    "-- materialize the corrected case with --replaces "
    "CASE_KEY=<failed copy id> on that run's stage and record its passing "
    "current configuration-and-target-qualified verdict on its terminal successor "
    "-- then re-run this supersede. If the item is leaving that run instead, "
    "remove it (yoke deployment-runs remove-item RUN-ID ITEM --reason TEXT), then "
    "re-run this supersede: "
    "the corrected requirement then owes its own proof on the next release."
)

#: Receipt note when no live membership holds a copy of the source.
PROOF_OWED_NOTICE = (
    "No run the item belongs to holds a copy of requirement {source_id}. "
    "Requirement {corrected_id} carries the obligation and owes its own proof: "
    "the next release carrying the item admits only its body, and done waits "
    "for that copy to pass."
)

_LINEAGE_COLUMNS = "id,item_id,plan_id,plan_case_key"


def is_source_retirement(broken: Mapping[str, Any]) -> bool:
    """Whether superseding *broken* retires a post-deploy item source."""
    return (
        not broken.get("deployment_run_id")
        and broken.get("item_id") is not None
        and str(broken.get("qa_phase") or "") == "post_deploy"
    )


def source_retirement_scope(row: Mapping[str, Any]) -> dict[str, Any]:
    """Item source identity uses its destination, not its admission snapshot."""
    from yoke_core.domain.deployment_member_post_deploy_admission import (
        requirement_target_environment,
    )

    return dict(
        row,
        execution_target_digest="",
        target_env=requirement_target_environment(
            row.get("target_env"), row.get("execution_target_json")
        ),
    )


def passing_run_replacement(conn: Any, source: Mapping[str, Any]) -> int | None:
    """The current passing terminal successor of a corrected admitted copy."""
    from yoke_core.domain.qa_obligation_settlement import effective_requirement
    from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run

    identity, params = admitted_requirement_identity_clause(source)
    environment = source_retirement_scope(source)["target_env"]
    copies = query_rows(
        conn,
        "SELECT id,target_env,execution_target_json FROM qa_requirements "
        f"WHERE deployment_run_id IS NOT NULL AND deployment_member_item_id=%s "
        "AND (superseded_by_requirement_id IS NOT NULL "
        "OR replacement_requirement_id IS NOT NULL) "
        f"AND {identity} ORDER BY id",
        (int(source["item_id"]), *params),
    )
    for copy in copies:
        if (
            environment
            and source_retirement_scope(dict(copy))["target_env"] != environment
        ):
            continue
        replacement_id = int(effective_requirement(conn, int(copy["id"]))["id"])
        if has_current_passing_run(conn, replacement_id):
            return replacement_id
    return None


def live_member_copies(conn: Any, source: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Copies of *source* on runs the item still belongs to that can still grade.

    A run the item was removed from, or one that failed or was cancelled,
    keeps its copies as history; no gate reads them for this item again.
    """
    identity, params = admitted_requirement_identity_clause(source, marker="%s")
    environment = source_retirement_scope(source)["target_env"]
    rows = query_rows(
        conn,
        "SELECT qr.id,qr.deployment_run_id,qr.target_env,qr.execution_target_json "
        "FROM qa_requirements qr "
        "JOIN deployment_run_items dri ON dri.run_id=qr.deployment_run_id "
        "AND dri.item_id=qr.deployment_member_item_id "
        "JOIN deployment_runs dr ON dr.id=qr.deployment_run_id "
        "WHERE qr.deployment_member_item_id=%s "
        "AND dr.status NOT IN ('failed','cancelled') "
        f"AND {identity} ORDER BY qr.id",
        (int(source["item_id"]), *params),
    )
    return [
        dict(row)
        for row in rows
        if not environment
        or source_retirement_scope(dict(row))["target_env"] == environment
    ]


def source_retirement_answer(
    conn: Any, source: Mapping[str, Any], *, corrected_id: int
) -> dict[str, Any]:
    """The proof that lets *source* retire, or the named refusal."""
    answer_id = passing_run_replacement(conn, source)
    if answer_id is not None:
        return {"run_replacement_requirement_id": answer_id}
    copies = live_member_copies(conn, source)
    if copies:
        return {
            "refusal": SOURCE_RETIREMENT_REFUSAL.format(
                source_id=int(source["id"]),
                copy_ids=", ".join(f"#{int(row['id'])}" for row in copies),
                run_ids=", ".join(
                    dict.fromkeys(str(row["deployment_run_id"]) for row in copies)
                ),
            )
        }
    return {
        "proof_owed_notice": PROOF_OWED_NOTICE.format(
            source_id=int(source["id"]), corrected_id=int(corrected_id)
        )
    }


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
        "SELECT id,method_id,workflow_transition_id,target_env,execution_target_json,waived_at,"
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
            target_env=source_retirement_scope(dict(source))["target_env"]
            or "<environment>",
        ),
    }


__all__ = [
    "NEXT_ADMISSION_NOTICE",
    "PROOF_OWED_NOTICE",
    "SOURCE_RETIREMENT_REFUSAL",
    "admitted_source_correction",
    "admitted_source_lineage",
    "is_source_retirement",
    "lineage_identity_clause",
    "live_member_copies",
    "passing_run_replacement",
    "source_retirement_answer",
    "source_retirement_scope",
]
