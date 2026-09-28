"""Declare a corrected QA case as the replacement for an exact failed one.

A case whose capture or config was wrong cannot be edited once it has
answered, so the fix is a corrected case beside it. Left there, every later
execution re-captured the broken case, the review bundle graded it again,
and the bundle failed on history nobody wanted re-judged; the stage then
waited until someone superseded the old rows by hand.

A replacement declared when the corrected case is materialized closes that
loop without a second state system. The failed row records which case now
carries its attempt (``replacement_requirement_id``) and keeps blocking:
nothing is discharged by the declaration itself. Rosters stop re-running the
declared row. When the replacement records a passing independent verdict,
:func:`discharge_declared_replacements` writes the ordinary supersession on
the same transaction as that verdict, so the stage gate re-evaluates against
an already-settled obligation. A replacement that fails or stays
undetermined leaves the failed row blocking with its own evidence intact; a
further correction declares itself the replacement of that failed attempt
and inherits every row still waiting on it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_obligation_settlement import obligation_settled
from yoke_core.domain.qa_requirement_supersession import (
    emit_supersession_event,
    latest_verdict,
    record_supersession,
    same_scope,
)

DISCHARGE_RATIONALE = (
    "declared replacement requirement {replacement_id} recorded a passing "
    "independent verdict"
)


class QaReplacementError(ValueError):
    """A replacement declaration was refused; the message names the recovery."""


def _row(conn: Any, requirement_id: int) -> dict[str, Any] | None:
    row = query_one(
        conn,
        "SELECT id,item_id,epic_id,task_num,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,execution_target_digest,workflow_transition_id,"
        "qa_phase,plan_case_key,blocking_mode,waived_at,retracted_at,"
        "superseded_by_requirement_id,replacement_requirement_id "
        "FROM qa_requirements WHERE id=%s",
        (int(requirement_id),),
    )
    return dict(row) if row is not None else None


def _replacement_for(
    conn: Any, failed: dict[str, Any], case_key: str, candidates: Sequence[int]
) -> dict[str, Any]:
    rows = [row for row in (_row(conn, rid) for rid in candidates) if row]
    matches = [
        row
        for row in rows
        if row["plan_case_key"] == case_key
        and int(row["id"]) != int(failed["id"])
        and not obligation_settled(row)
        and not row["replacement_requirement_id"]
    ]
    if len(matches) != 1:
        found = ", ".join(str(row["id"]) for row in matches) or "none"
        raise QaReplacementError(
            f"replacement case key {case_key!r} for requirement {failed['id']} "
            f"matched {found} among the cases this materialization produced. "
            "Name the key of exactly one corrected case in this plan; the "
            "materialized cases are unchanged, so re-run the same command with "
            "the corrected --replaces."
        )
    replacement = matches[0]
    mismatches = same_scope(failed, replacement)
    if mismatches:
        raise QaReplacementError(
            f"requirement {replacement['id']} cannot replace requirement "
            f"{failed['id']}: {'; '.join(mismatches)}. Materialize the corrected "
            "case for the failed case's own run, stage, member and target (or "
            "item, transition and phase)."
        )
    if str(replacement.get("blocking_mode") or "") != "blocking":
        raise QaReplacementError(
            f"requirement {replacement['id']} is not blocking, so no gate grades "
            f"it and it cannot carry requirement {failed['id']}'s obligation."
        )
    return replacement


def point_at_replacement(conn: Any, failed_id: int, replacement_id: int) -> None:
    """Make the corrected case carry the failed row's attempt.

    Every row still waiting on the failed one as its own replacement moves
    to the corrected case too, so a correction of a correction inherits the
    whole chain instead of stranding the first failure.
    """
    conn.execute(
        "UPDATE qa_requirements SET replacement_requirement_id=%s "
        "WHERE (id=%s OR replacement_requirement_id=%s) "
        "AND superseded_by_requirement_id IS NULL",
        (int(replacement_id), int(failed_id), int(failed_id)),
    )


def declare_replacements(
    conn: Any,
    replacements: Iterable[dict[str, Any]],
    *,
    materialized_requirement_ids: Sequence[int],
) -> list[dict[str, int]]:
    """Record each failed row's declared replacement; the caller commits."""
    declared: list[dict[str, int]] = []
    for entry in replacements:
        failed_id = int(entry["requirement_id"])
        failed = _row(conn, failed_id)
        if failed is None:
            raise QaReplacementError(f"replaced requirement {failed_id} not found")
        if obligation_settled(failed):
            raise QaReplacementError(
                f"requirement {failed_id} is already waived, superseded or "
                "retracted; it owes nothing a replacement could answer."
            )
        if latest_verdict(conn, failed_id) == "pass":
            raise QaReplacementError(
                f"requirement {failed_id} already passed; declare a replacement "
                "only for a case that failed or could not be judged."
            )
        replacement = _replacement_for(
            conn, failed, str(entry["case_key"]), materialized_requirement_ids
        )
        replacement_id = int(replacement["id"])
        point_at_replacement(conn, failed_id, replacement_id)
        declared.append(
            {"requirement_id": failed_id, "replacement_requirement_id": replacement_id}
        )
    return declared


def discharge_declared_replacements(
    conn: Any, passing_requirement_ids: Iterable[int]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Supersede every row waiting on a replacement that just passed.

    Runs on the verdict's own open transaction. Returns ``(receipt, row)``
    pairs for :func:`announce_discharges` once the caller has committed.
    """
    discharged: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for replacement_id in sorted({int(rid) for rid in passing_requirement_ids}):
        waiting = query_rows(
            conn,
            "SELECT id FROM qa_requirements WHERE replacement_requirement_id=%s "
            "AND superseded_by_requirement_id IS NULL AND waived_at IS NULL "
            "AND retracted_at IS NULL ORDER BY id",
            (replacement_id,),
        )
        # A row settled another way since the declaration keeps the record
        # that settled it; anything else refusing here is a broken invariant
        # and rolls back the verdict rather than hiding the failure.
        for row in waiting:
            discharged.append(
                record_supersession(
                    conn,
                    requirement_id=int(row["id"]),
                    superseded_by_requirement_id=replacement_id,
                    rationale=DISCHARGE_RATIONALE.format(replacement_id=replacement_id),
                    source="agent",
                )
            )
    return discharged


def announce_discharges(
    conn: Any, discharged: Sequence[tuple[dict[str, Any], dict[str, Any]]]
) -> None:
    """Emit supersession telemetry after the discharging verdict committed."""
    for receipt, row in discharged:
        emit_supersession_event(conn, receipt, row)


__all__ = [
    "DISCHARGE_RATIONALE",
    "QaReplacementError",
    "announce_discharges",
    "declare_replacements",
    "discharge_declared_replacements",
    "point_at_replacement",
]
