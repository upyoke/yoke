"""Discharge a broken frozen QA case with a corrected one that passed.

A deployment-run requirement row is an immutable acceptance snapshot: once
it exists it cannot be corrected in place. Before this module the only exit
for a row that was defective when it froze was an operator waiver, which
records "we chose not to require this" -- a claim nobody wants attached to
a case that a corrected sibling actually proved.

Supersession is the honest alternative. A second case bound to the same
run, stage, member and execution target, which has itself passed, may be
recorded as discharging the broken one. The broken row stays exactly as it
is, so the history of what went wrong survives; what changes is that the
stage gate reads its obligation as met by the named passing row rather
than as unmet.

The gate never has to trust the link on its own: the superseding row is in
the same evaluated scope, so it is graded on its own evidence in the same
pass. A link to a row that later stops passing therefore cannot launder a
failure through -- that row fails for itself.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import iso8601_now, query_one, query_rows
from yoke_core.domain.qa_events import emit_qa_requirement_event


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
        "SELECT id,item_id,epic_id,task_num,"
        "deployment_run_id,deployment_stage,deployment_member_item_id,"
        "execution_target_digest,blocking_mode,plan_case_key,method_id,"
        "qa_kind,qa_phase,"
        "waived_at,superseded_by_requirement_id "
        "FROM qa_requirements WHERE id=%s",
        (int(requirement_id),),
    )
    if row is None:
        raise LookupError(f"{label} requirement {requirement_id} not found")
    return dict(row)


def _same_scope(broken: dict[str, Any], corrected: dict[str, Any]) -> list[str]:
    """Every way the two rows fail to answer for the same obligation."""
    mismatches: list[str] = []
    for column, label in (
        ("deployment_run_id", "deployment run"),
        ("deployment_stage", "deployment stage"),
        ("deployment_member_item_id", "deployment member"),
        ("execution_target_digest", "execution target"),
    ):
        if str(broken.get(column) or "") != str(corrected.get(column) or ""):
            mismatches.append(
                f"{label} differs ({broken.get(column)!r} vs {corrected.get(column)!r})"
            )
    return mismatches


def latest_verdict(conn: Any, requirement_id: int) -> str:
    row = query_one(
        conn,
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (int(requirement_id),),
    )
    if row is None:
        return ""
    return str(row["verdict"] or "")


def supersede_requirement(
    conn: Any,
    *,
    requirement_id: int,
    superseded_by_requirement_id: int,
    rationale: str,
    source: str = "agent",
    db_path: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Record that a passing sibling case discharges this frozen one.

    Refuses rather than guessing: the two rows must be the same
    obligation, the replacement must be a real blocking case that has
    passed, and neither may already be discharged another way. Every
    refusal names what to do instead.
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

    broken = _requirement(conn, requirement_id, label="superseded")
    corrected = _requirement(conn, superseded_by_requirement_id, label="superseding")

    if not str(broken.get("deployment_run_id") or ""):
        raise QaSupersessionError(
            f"requirement {requirement_id} is not bound to a deployment run; "
            "supersession exists for frozen run-bound cases. Correct a live "
            "item requirement in place with yoke qa requirement update instead."
        )
    mismatches = _same_scope(broken, corrected)
    if mismatches:
        raise QaSupersessionError(
            f"requirement {superseded_by_requirement_id} does not answer for "
            f"requirement {requirement_id}'s obligation: {'; '.join(mismatches)}. "
            "Bind the corrected case to the same run, stage, member and "
            "deployment target, then record the supersession."
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
    if corrected.get("superseded_by_requirement_id"):
        raise QaSupersessionError(
            f"requirement {superseded_by_requirement_id} is itself superseded "
            f"by requirement {corrected['superseded_by_requirement_id']}. Name "
            "that case directly rather than chaining through a discharged one."
        )
    verdict = latest_verdict(conn, int(superseded_by_requirement_id))
    if verdict != "pass":
        raise QaSupersessionError(
            f"requirement {superseded_by_requirement_id} latest verdict is "
            f"{verdict or 'missing'}, not pass. Run the corrected case to a "
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

    now = iso8601_now()
    conn.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=%s,"
        "superseded_at=%s,supersession_rationale=%s,supersession_source=%s "
        "WHERE id=%s",
        (
            int(superseded_by_requirement_id),
            now,
            rationale,
            str(source),
            int(requirement_id),
        ),
    )
    if commit:
        conn.commit()

    emit_qa_requirement_event(
        conn,
        db_path=db_path,
        event_name="QARequirementSuperseded",
        requirement_id=int(requirement_id),
        qa_kind=str(broken.get("qa_kind") or ""),
        qa_phase=str(broken.get("qa_phase") or ""),
        rationale=rationale,
        source=str(source),
        target_row=broken,
        extra_detail={
            "superseded_by_requirement_id": int(superseded_by_requirement_id)
        },
    )
    return {
        "requirement_id": int(requirement_id),
        "superseded_by_requirement_id": int(superseded_by_requirement_id),
        "superseded_at": now,
        "supersession_rationale": rationale,
        "supersession_source": str(source),
    }


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
    "latest_verdict",
    "supersede_requirement",
    "supersession_history",
]
