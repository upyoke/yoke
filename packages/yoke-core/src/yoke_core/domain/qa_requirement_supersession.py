"""Discharge a broken frozen QA case with a corrected one that passed.

A deployment-run requirement row is an immutable acceptance snapshot: once
it exists it cannot be corrected in place. Before this module the only exit
for a row that was defective when it froze was an operator waiver, which
records "we chose not to require this" -- a claim nobody wants attached to
a case that a corrected sibling actually proved.

Supersession is the honest alternative. A second case bound to the same
obligation -- the same run, stage, member and execution target for a
run-bound case; the same item, transition, phase and execution target for an
item-bound one -- which has itself passed, may be recorded as discharging
the broken one. A replacement declared when the corrected case was
materialized records this automatically once it passes
(:mod:`yoke_core.domain.qa_requirement_replacement`). The broken row stays exactly as it
is, so the history of what went wrong survives; what changes is that the
stage gate reads its obligation as met by the named passing row rather
than as unmet.

The gate never has to trust the link on its own: the superseding row is in
the same evaluated scope, so it is graded on its own evidence in the same
pass. A link to a row that later stops passing therefore cannot launder a
failure through -- that row fails for itself.

What superseding an admitted copy deliberately does NOT do is reach the
item requirement the copy was frozen from. That row is a real outstanding
obligation and discharging it from here would drop it forever. But leaving
it unmentioned was how a correction failed to stick: the next release
admitted a fresh copy of the same defective body. So the receipt names that
row and the command that retires it, at the one moment the operator holds
the corrected body. Retiring it is its own explicit supersession of the
source by a corrected item requirement
(:mod:`yoke_core.domain.qa_requirement_source_retirement`).
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import (
    instant_parameter,
    utc_now,
    query_one,
    query_rows,
)
from yoke_core.domain.qa_events import emit_qa_requirement_event
from yoke_core.domain.qa_obligation_settlement import requirement_retracted_at_select
from yoke_core.domain.qa_requirement_source_retirement import (
    SOURCE_RETIREMENT_REFUSAL,
    admitted_source_correction,
    is_source_retirement,
    passing_run_replacement,
)


SUPERSESSION_SOURCES = ("agent", "operator")

#: Columns that together answer "is this row discharged, and by what".
SUPERSESSION_FIELDS = (
    "superseded_by_requirement_id",
    "superseded_at",
    "supersession_rationale",
    "supersession_source",
)


class QaSupersessionError(ValueError):
    """A supersession was refused; the message names the recovery."""


def _requirement(conn: Any, requirement_id: int, *, label: str) -> dict[str, Any]:
    row = query_one(
        conn,
        "SELECT id,item_id,epic_id,task_num,plan_id,"
        "deployment_run_id,deployment_stage,deployment_member_item_id,"
        "execution_target_digest,target_env,host_baseline,blocking_mode,plan_case_key,method_id,"
        "qa_kind,qa_phase,workflow_transition_id,replacement_requirement_id,"
        f"waived_at,superseded_by_requirement_id,{requirement_retracted_at_select(conn)} "
        "FROM qa_requirements WHERE id=%s",
        (int(requirement_id),),
    )
    if row is None:
        raise LookupError(f"{label} requirement {requirement_id} not found")
    return dict(row)


_RUN_SCOPE = (
    ("deployment_run_id", "deployment run"),
    ("deployment_stage", "deployment stage"),
    ("deployment_member_item_id", "deployment member"),
    ("execution_target_digest", "execution target"),
    ("target_env", "target environment"),
    ("host_baseline", "host baseline"),
)
_ITEM_SCOPE = (
    ("deployment_run_id", "deployment run"),
    ("item_id", "item"),
    ("epic_id", "epic"),
    ("task_num", "task"),
    ("workflow_transition_id", "workflow transition"),
    ("qa_phase", "QA phase"),
    ("execution_target_digest", "execution target"),
    ("target_env", "target environment"),
    ("host_baseline", "host baseline"),
)


def requirement_scope(row: dict[str, Any]) -> tuple[str, ...]:
    """Canonical obligation scope, shared by comparison and mutation locking."""
    fields = _RUN_SCOPE if row.get("deployment_run_id") else _ITEM_SCOPE
    return tuple(str(row.get(column) or "") for column, _label in fields)


def same_scope(broken: dict[str, Any], corrected: dict[str, Any]) -> list[str]:
    """Every way the two rows fail to answer for the same obligation."""
    mismatches: list[str] = []
    scope = _RUN_SCOPE if broken.get("deployment_run_id") else _ITEM_SCOPE
    for column, label in scope:
        if str(broken.get(column) or "") != str(corrected.get(column) or ""):
            mismatches.append(
                f"{label} differs ({broken.get(column)!r} vs {corrected.get(column)!r})"
            )
    return mismatches


def latest_verdict(conn: Any, requirement_id: int) -> str:
    from yoke_core.domain.qa_latest_execution import latest_executions

    row = latest_executions(conn, [requirement_id]).get(int(requirement_id))
    return str(row["verdict"] or "") if row is not None else ""


def record_supersession(
    conn: Any,
    *,
    requirement_id: int,
    superseded_by_requirement_id: int,
    rationale: str,
    source: str = "agent",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate and write one supersession on the caller's open transaction.

    Refuses rather than guessing: the two rows must be the same
    obligation, the replacement must be a real blocking case that has
    passed, and neither may already be discharged another way. A
    post-deploy item source never runs, so retiring one needs a passing run
    replacement of its admitted copy instead. Every refusal names what to do
    instead. Returns the receipt and the discharged row; the caller commits
    and then emits the event.
    """
    rationale = str(rationale or "").strip()
    if not rationale:
        raise QaSupersessionError(
            "supersession requires a rationale explaining why the corrected "
            "case answers the frozen one's obligation"
        )
    if str(source) not in SUPERSESSION_SOURCES:
        raise QaSupersessionError(
            f"supersession source must be one of {', '.join(SUPERSESSION_SOURCES)}"
        )
    if int(requirement_id) == int(superseded_by_requirement_id):
        raise QaSupersessionError(
            f"requirement {requirement_id} cannot supersede itself; name the "
            "corrected case that actually passed"
        )

    from yoke_core.domain.qa_requirement_scope import lock_requirement_scope
    from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run

    lock_requirement_scope(conn, requirement_id)
    broken = _requirement(conn, requirement_id, label="superseded")
    corrected = _requirement(conn, superseded_by_requirement_id, label="superseding")

    mismatches = same_scope(broken, corrected)
    if mismatches:
        raise QaSupersessionError(
            f"requirement {superseded_by_requirement_id} does not answer for "
            f"requirement {requirement_id}'s obligation: {'; '.join(mismatches)}. "
            "Bind the corrected case to the same run, stage, member and "
            "deployment target (or, for an item case, the same item, "
            "transition, phase and target), then record the supersession."
        )
    if str(corrected.get("blocking_mode") or "") != "blocking":
        raise QaSupersessionError(
            f"requirement {superseded_by_requirement_id} is not blocking, so "
            "the stage gate never grades it. Only a blocking case can carry "
            "another case's blocking obligation."
        )
    if corrected.get("waived_at"):
        raise QaSupersessionError(
            f"requirement {superseded_by_requirement_id} is itself waived, so "
            "it proves nothing. Name a case that actually passed."
        )
    for column in ("superseded_by_requirement_id", "replacement_requirement_id"):
        if corrected.get(column):
            raise QaSupersessionError(
                f"requirement {superseded_by_requirement_id} is itself replaced "
                f"by requirement {corrected[column]}. Name that case directly "
                "rather than chaining through an earlier attempt."
            )
    run_answer: dict[str, int] = {}
    if is_source_retirement(broken):
        answer_id = passing_run_replacement(conn, broken)
        if answer_id is None:
            raise QaSupersessionError(
                SOURCE_RETIREMENT_REFUSAL.format(source_id=int(requirement_id))
            )
        run_answer = {"run_replacement_requirement_id": answer_id}
    elif not has_current_passing_run(conn, int(superseded_by_requirement_id)):
        verdict = latest_verdict(conn, int(superseded_by_requirement_id))
        raise QaSupersessionError(
            f"requirement {superseded_by_requirement_id} has no completed current "
            f"configuration-and-target-qualified pass (recorded verdict: {verdict or 'missing'}). Run the corrected case to a "
            "recorded pass with evidence, then record the supersession: "
            f"yoke qa case run --requirement-id {superseded_by_requirement_id}"
        )
    if broken.get("waived_at"):
        raise QaSupersessionError(
            f"requirement {requirement_id} is already waived; the waiver "
            "already discharged it and supersession would leave two "
            "conflicting records of why."
        )
    existing = broken.get("superseded_by_requirement_id")
    if existing and int(existing) != int(superseded_by_requirement_id):
        raise QaSupersessionError(
            f"requirement {requirement_id} is already superseded by "
            f"requirement {existing}. A frozen case records one discharge; "
            "supersede the newer case instead if that one is wrong."
        )

    now = utc_now()
    conn.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=%s,"
        "superseded_at=%s,supersession_rationale=%s,supersession_source=%s "
        "WHERE id=%s",
        (
            int(superseded_by_requirement_id),
            instant_parameter(conn, now),
            rationale,
            str(source),
            int(requirement_id),
        ),
    )
    return {
        "requirement_id": int(requirement_id),
        "superseded_by_requirement_id": int(superseded_by_requirement_id),
        "superseded_at": now,
        "supersession_rationale": rationale,
        "supersession_source": str(source),
        **admitted_source_correction(conn, broken),
        **run_answer,
    }, broken


def emit_supersession_event(
    conn: Any,
    receipt: dict[str, Any],
    broken: dict[str, Any],
    *,
    db_path: str | None = None,
) -> None:
    """Best-effort telemetry for a supersession the caller already committed."""
    emit_qa_requirement_event(
        conn,
        db_path=db_path,
        event_name="QARequirementSuperseded",
        requirement_id=int(receipt["requirement_id"]),
        qa_kind=str(broken.get("qa_kind") or ""),
        qa_phase=str(broken.get("qa_phase") or ""),
        rationale=str(receipt["supersession_rationale"]),
        source=str(receipt["supersession_source"]),
        target_row=broken,
        extra_detail={
            "superseded_by_requirement_id": int(receipt["superseded_by_requirement_id"])
        },
    )


def supersede_requirement(
    conn: Any,
    *,
    requirement_id: int,
    superseded_by_requirement_id: int,
    rationale: str,
    source: str = "agent",
    db_path: str | None = None,
) -> dict[str, Any]:
    """Record, commit and announce that a passing sibling discharges this one."""
    receipt, broken = record_supersession(
        conn,
        requirement_id=requirement_id,
        superseded_by_requirement_id=superseded_by_requirement_id,
        rationale=rationale,
        source=source,
    )
    conn.commit()
    emit_supersession_event(conn, receipt, broken, db_path=db_path)
    return receipt


def supersession_history(conn: Any, *, run_id: str) -> list[dict[str, Any]]:
    """Every supersession recorded against one deployment run, oldest first."""
    return [
        dict(row)
        for row in query_rows(
            conn,
            "SELECT id,plan_case_key,deployment_stage,deployment_member_item_id,"
            "superseded_by_requirement_id,superseded_at,supersession_rationale,"
            "supersession_source FROM qa_requirements "
            "WHERE deployment_run_id=%s AND superseded_by_requirement_id IS NOT NULL "
            "ORDER BY superseded_at,id",
            (str(run_id),),
        )
    ]


__all__ = [
    "SUPERSESSION_FIELDS",
    "SUPERSESSION_SOURCES",
    "QaSupersessionError",
    "emit_supersession_event",
    "latest_verdict",
    "record_supersession",
    "same_scope",
    "supersede_requirement",
    "supersession_history",
]
