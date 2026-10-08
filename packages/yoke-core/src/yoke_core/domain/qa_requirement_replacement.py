"""Declare a corrected case and immediately move grading to its successor.

Historical captures and discharge audit remain intact. Only a current passing
successor records automatic supersession; delayed review of an older capture
cannot discharge the chain. Graph validation belongs to the declaring transaction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_obligation_settlement import obligation_settled
from yoke_core.domain.qa_requirement_supersession import (
    emit_supersession_event,
    latest_verdict,
    record_supersession,
    same_scope,
)
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.qa_requirement_scope import lock_requirement_scope

_REPLACEABLE_DEPLOYMENT_VERDICTS = {"fail", "error"}

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
        "deployment_member_item_id,execution_target_digest,target_env,host_baseline,workflow_transition_id,"
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
    """Validate a same-scope acyclic edge under row locks, then transfer grading."""
    lock_requirement_scope(conn, failed_id)
    locked = query_rows(
        conn,
        "SELECT id FROM qa_requirements WHERE id IN (%s,%s) ORDER BY id FOR UPDATE",
        (int(failed_id), int(replacement_id)),
    )
    if len(locked) != 2:
        raise QaReplacementError(
            "replacement_graph_invalid: missing or self-linked requirement"
        )
    failed = _row(conn, failed_id)
    seen = {int(failed_id)}
    successor_id = int(replacement_id)
    while successor_id:
        if successor_id in seen:
            raise QaReplacementError(
                "replacement_graph_invalid: replacement cycle; correct the declaration"
            )
        seen.add(successor_id)
        successor = _row(conn, successor_id)
        if successor is None or same_scope(failed, successor):
            raise QaReplacementError(
                "replacement_graph_invalid: missing or incompatible successor; bind the same scope and target"
            )
        successor_id = int(
            successor.get("replacement_requirement_id")
            or successor.get("superseded_by_requirement_id")
            or 0
        )
    conn.execute(
        "UPDATE qa_requirements SET replacement_requirement_id=%s "
        "WHERE id=%s "
        "AND superseded_by_requirement_id IS NULL",
        (int(replacement_id), int(failed_id)),
    )


def declare_existing_replacement(
    conn: Any, *, failed_id: int, replacement_id: int
) -> dict[str, Any]:
    """Atomically attach an already-created corrected case to a failed one.

    A deployment-run case must belong to the run's executing stage; an item
    case must share the failed row's item, transition and phase.
    """
    failed = _row(conn, failed_id)
    corrected = _row(conn, replacement_id)
    if failed is None or corrected is None:
        raise QaReplacementError(
            f"failed requirement {failed_id} or corrected requirement "
            f"{replacement_id} is missing; inspect both with `yoke qa requirement get`"
        )
    mismatches = same_scope(failed, corrected)
    if mismatches:
        raise QaReplacementError(
            f"corrected requirement {replacement_id} cannot replace {failed_id}: "
            f"{'; '.join(mismatches)}. Bind it to the same run, stage, member "
            "and pinned execution target (or item, transition and phase)."
        )
    if str(corrected.get("blocking_mode") or "") != "blocking" or obligation_settled(
        corrected
    ):
        raise QaReplacementError(
            f"corrected requirement {replacement_id} must be an active blocking case"
        )
    receipt = _existing_replacement_receipt(failed, replacement_id)
    if failed.get("replacement_requirement_id") == replacement_id:
        return receipt
    if obligation_settled(failed) or failed.get("replacement_requirement_id"):
        raise QaReplacementError(
            f"requirement {failed_id} is settled or already replaced; "
            "inspect its current replacement before retrying"
        )
    if latest_verdict(conn, failed_id) not in _REPLACEABLE_DEPLOYMENT_VERDICTS:
        raise QaReplacementError(
            f"requirement {failed_id} has no fail or error verdict; "
            "run the case before correction and replace only a case that "
            "failed or could not be judged."
        )
    if latest_verdict(conn, replacement_id):
        raise QaReplacementError(
            f"corrected requirement {replacement_id} already has a verdict; "
            "use ordinary supersession after a pass or create a fresh case"
        )
    if failed.get("deployment_run_id"):
        run = query_one(
            conn,
            "SELECT status,current_stage FROM deployment_runs WHERE id=%s FOR UPDATE",
            (str(failed["deployment_run_id"]),),
        )
        if (
            run is None
            or run["status"] != "executing"
            or run["current_stage"] != failed["deployment_stage"]
        ):
            raise QaReplacementError(
                f"run {failed['deployment_run_id']} is not executing stage "
                f"{failed['deployment_stage']}; inspect the run before correction"
            )
    point_at_replacement(conn, failed_id, replacement_id)
    return receipt


def _existing_replacement_receipt(
    failed: Mapping[str, Any], replacement_id: int
) -> dict[str, Any]:
    """The declaration receipt, in the failed row's own subject columns."""
    receipt: dict[str, Any] = {
        "requirement_id": int(failed["id"]),
        "replacement_requirement_id": int(replacement_id),
    }
    if failed.get("deployment_run_id"):
        receipt.update(
            deployment_run_id=str(failed["deployment_run_id"]),
            deployment_stage=str(failed["deployment_stage"]),
            deployment_member_item_id=failed.get("deployment_member_item_id"),
        )
    else:
        receipt.update(
            item_id=failed.get("item_id"),
            workflow_transition_id=failed.get("workflow_transition_id"),
        )
    return receipt


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
        replacement = _replacement_for(
            conn, failed, str(entry["case_key"]), materialized_requirement_ids
        )
        replacement_id = int(replacement["id"])
        if failed.get("replacement_requirement_id") == replacement_id:
            declared.append(
                {
                    "requirement_id": failed_id,
                    "replacement_requirement_id": replacement_id,
                }
            )
            continue
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
        if (
            failed.get("deployment_run_id")
            and latest_verdict(conn, failed_id) not in _REPLACEABLE_DEPLOYMENT_VERDICTS
        ):
            raise QaReplacementError(
                f"deployment requirement {failed_id} has no fail or error verdict; "
                "run its admitted case before declaring a correction."
            )
        if failed.get("replacement_requirement_id"):
            raise QaReplacementError(
                f"requirement {failed_id} already points to corrected case "
                f"{failed['replacement_requirement_id']}; correct that case instead."
            )
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
    pairs for :func:`announce_discharges` once the caller has committed. A
    database that has not converged the replacement column yet cannot hold a
    row waiting on a replacement, so its verdict writes discharge nothing.
    """
    discharged: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if not _column_exists(conn, "qa_requirements", "replacement_requirement_id"):
        return discharged
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


def replacement_note(row: Mapping[str, Any]) -> str:
    """Refusal suffix naming the corrected case a failed row is waiting on."""
    replacement_id = row.get("replacement_requirement_id")
    if not replacement_id:
        return ""
    return (
        f"; declared replacement #{replacement_id} now carries its grading obligation"
    )


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
    "declare_existing_replacement",
    "discharge_declared_replacements",
    "point_at_replacement",
    "replacement_note",
]
