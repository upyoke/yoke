"""A run reads succeeded only after every cleared member has closed.

A run whose shared gates passed used to commit ``succeeded`` and close its
members afterwards, so any refusal, failed write, or interrupted process in
between left a green run over members still at their release wait.

Settlement reverses that order through one durable, non-terminal state. The
run stays ``executing`` and records ``settling_at``; completion authority
reads a settling run as delivered, so each member's own done gates can pass.

Settlement then runs in two phases.

**Commit: one transaction for every member.** A shared gate passes for the
run, not for one member at a time. First each cleared member's
prerequisites are committed — residue superseded, its delivery rung
stamped, and its status preflight run — none of which closes anything, all
of it idempotent, and all of it read by done gates on their own
connections. Then every member's terminal status and claim release is
written on the settlement's own connection and committed once. Each member
is written inside its own savepoint, so one that refuses is rolled back
alone and every blocker is still named; any refusal then rolls back the
whole set. Members therefore close together or not at all, whatever changes
mid-way and however the process stops.

**Effects: after the commit, idempotent and replayable.** GitHub sync,
terminal lane cleanup, and ending the holders' now-empty sessions run over
every member the run has closed. A failure here never reopens a closed
member: the run stays ``executing`` and settling, and the next re-drive of
``status succeeded`` (or the replay a cleared blocker triggers) finds the
commit phase already done and finishes the effects before the run is
marked succeeded.
"""

from __future__ import annotations

import io
from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now

#: Why a member that could itself close is still open. Reported instead of a
#: blocker of its own, so nobody repairs a member that has nothing wrong.
HELD_WITH_RUN = (
    "it could close, and is held only because a sibling member could not; "
    "a shared gate closes every member or none"
)

_MEMBER_SAVEPOINT = "_yoke_settle_member"


def mark_settling(conn: Any, run_id: str) -> None:
    """Record, once and durably, that this run is settling its members."""
    conn.execute(
        "UPDATE deployment_runs SET settling_at=COALESCE(settling_at, %s) "
        "WHERE id=%s AND status='executing'",
        (iso8601_now(), run_id),
    )
    conn.commit()


def _unsettled_reason(conn: Any, run_id: str, item_id: int) -> str:
    """Why a member this run must close is still at its release wait."""
    from yoke_core.domain.deployment_delivery_close_out_notice import (
        delivery_now_discharged,
    )
    from yoke_core.domain.no_obligation_member_close_out import (
        satisfied_delivery_member,
    )

    if not delivery_now_discharged(conn, item_id):
        return (
            "its delivery fact does not read delivered by this run; read "
            f"`yoke deployment-runs get {run_id}` and repair the run's "
            "completion authority for it"
        )
    if not satisfied_delivery_member(conn, item_id=item_id, run_id=run_id):
        return (
            "its post-deploy obligations on this run are not all answered; "
            "pass or waive each one, or record `yoke qa post-deploy "
            "record-no-obligation` when nothing is observable once deployed"
        )
    return "its close-out has not completed"


def _final_members(conn: Any, run_id: str, *, at_wait: bool) -> list[dict[str, Any]]:
    """Members this run is the final delivery of, at their wait or closed."""
    from yoke_core.domain.deployment_delivery_close_out_notice import run_members
    from yoke_core.domain.deployment_member_run_coverage import member_run_coverage
    from yoke_core.domain.deployment_run_composition_freeze import (
        DELIVERY_INTENT_PROGRESS,
    )
    from yoke_core.domain.release_wait_ownership import item_at_release_wait
    from yoke_core.domain.standalone_item_merge_evidence import CLOSED_OUT_STATUS
    from yoke_contracts.public_ref import format_item_ref

    members: list[dict[str, Any]] = []
    for row in run_members(conn, run_id):
        if row["delivery_intent"] == DELIVERY_INTENT_PROGRESS:
            continue
        status = str(row["status"] or "")
        if at_wait and not item_at_release_wait(row, status):
            continue
        if not at_wait and status != CLOSED_OUT_STATUS:
            continue
        item_id = int(row["item_id"])
        if not member_run_coverage(conn, run_id=run_id, item_id=item_id).closes:
            continue
        members.append(
            {
                "item_id": item_id,
                "public_ref": format_item_ref(
                    None, row["public_item_prefix"], row["project_sequence"]
                ),
            }
        )
    return members


def _prepared_members(
    conn: Any, run_id: str, members: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Commit every member's close prerequisites; name each that is blocked.

    Residue goes first: an item-level execution that recorded nothing is
    superseded, because the walk that would abort it is the one that
    already finished as this run's own scoped item QA. Then each member
    whose scoped QA this run settled commits its delivery rung and status
    preflight. Everything here is idempotent and closes nothing.
    """
    from yoke_core.domain.delivery_member_close_steps import prepare_member_close
    from yoke_core.domain.no_obligation_member_close_out import (
        satisfied_delivery_member,
    )
    from yoke_core.domain.qa_resultless_execution_supersession import (
        supersede_resultless_item_executions,
    )

    ready: list[dict[str, Any]] = []
    refusals: dict[int, str] = {}
    for member in members:
        item_id = int(member["item_id"])
        public_ref = str(member["public_ref"])
        unresolved = supersede_resultless_item_executions(
            conn, item_id=item_id, run_id=run_id, public_ref=public_ref
        )
        if unresolved:
            refusals[item_id] = "; ".join(unresolved)
            continue
        if not satisfied_delivery_member(conn, item_id=item_id, run_id=run_id):
            continue
        try:
            refusal = prepare_member_close(conn, item_id=item_id, public_ref=public_ref)
        except Exception as exc:  # noqa: BLE001 - named as this member's blocker
            conn.rollback()
            refusal = str(exc) or exc.__class__.__name__
        if refusal:
            refusals[item_id] = refusal
        else:
            ready.append(member)
    return ready, refusals


class SettlementTransactionLost(RuntimeError):
    """A member's status write ended the transaction settlement owns."""


def _end_savepoint(conn: Any, public_ref: str, *, keep: bool) -> None:
    """Release or roll back a member's savepoint, refusing a lost one.

    The savepoint only disappears when something inside the member's status
    write committed or rolled back the shared connection — which may already
    have committed earlier members on their own — so that is never absorbed.
    """
    verb = "RELEASE SAVEPOINT" if keep else "ROLLBACK TO SAVEPOINT"
    try:
        conn.execute(f"{verb} {_MEMBER_SAVEPOINT}")
    except Exception as exc:  # noqa: BLE001 - re-raised with its diagnosis
        raise SettlementTransactionLost(
            f"{public_ref}'s status write ended the settlement transaction "
            f"({exc}); members written before it may have committed on their "
            "own. A caller-owned status write must never commit or roll back "
            "its connection: fix the step that did, then re-drive the run"
        ) from exc


def _stage_members(
    conn: Any, members: list[dict[str, Any]], refusals: dict[int, str]
) -> list[Any]:
    """Write every prepared member's close into the open transaction.

    Each member is written inside its own savepoint, so a refusal rolls back
    that member alone and the rest are still asked; every blocker is named.
    """
    from yoke_core.domain.delivery_member_close_steps import stage_member_close

    staged: list[Any] = []
    for member in members:
        item_id = int(member["item_id"])
        public_ref = str(member["public_ref"])
        conn.execute(f"SAVEPOINT {_MEMBER_SAVEPOINT}")
        try:
            written = stage_member_close(conn, item_id=item_id, public_ref=public_ref)
        except Exception as exc:  # noqa: BLE001 - named as this member's blocker
            _end_savepoint(conn, public_ref, keep=False)
            refusals[item_id] = str(exc) or exc.__class__.__name__
            continue
        _end_savepoint(conn, public_ref, keep=not written.refusal)
        if written.refusal:
            refusals[item_id] = written.refusal
        else:
            staged.append(written)
    return staged


def _settle_refusal(run_id: str, unsettled: list[str], *, closed: bool) -> str:
    if closed:
        held = (
            "every member is already closed and stays closed; only its "
            "post-close effects are outstanding"
        )
    else:
        held = (
            "none is closed: the run stays executing and settling and every "
            "member keeps its claim and lane"
        )
    return (
        f"Error: cannot set status=succeeded -- run {run_id} is settling and "
        f"{len(unsettled)} member(s) it must close have not settled: "
        f"{'; '.join(unsettled)}. A shared gate passes for the run, not for "
        f"one member at a time, so {held}. Repair each named member; "
        "settlement replays on its own once the last blocker clears. If the "
        "run stays executing, re-drive it under the project deploy lock with "
        f"`yoke deployment-runs update {run_id} status succeeded`."
    )


def _commit_phase(conn: Any, run_id: str) -> tuple[list[Any], Optional[str]]:
    """Close every cleared member in one commit, or none of them."""
    from yoke_core.domain.deployment_delivery_close_out_notice import (
        cleared_release_waits,
    )

    ready, refusals = _prepared_members(
        conn, run_id, cleared_release_waits(conn, run_id)
    )
    try:
        staged = _stage_members(conn, ready, refusals)
    except SettlementTransactionLost as exc:
        conn.rollback()
        return [], _settle_refusal(run_id, [str(exc)], closed=False)
    if not refusals and not _final_members(conn, run_id, at_wait=True):
        conn.commit()
        return staged, None
    conn.rollback()
    held = {int(written.item_id) for written in staged}
    unsettled = [
        f"{member['public_ref']}: "
        + (
            refusals.get(member["item_id"])
            or (HELD_WITH_RUN if member["item_id"] in held else "")
            or _unsettled_reason(conn, run_id, member["item_id"])
        )
        for member in _final_members(conn, run_id, at_wait=True)
    ]
    return [], _settle_refusal(run_id, unsettled, closed=False)


def _effects_phase(conn: Any, run_id: str, staged: list[Any]) -> Optional[str]:
    """Run every closed member's effects; name each one that did not finish.

    The members this run has closed are read from the database rather than
    from ``staged``, so a replay finishes effects an earlier pass left
    undone. Only the pass that committed a member holds its effect receipt.
    """
    from yoke_core.domain.delivery_member_close_steps import (
        run_closed_member_effects,
    )

    receipts = {int(written.item_id): written.receipt for written in staged}
    failed: list[str] = []
    for member in _final_members(conn, run_id, at_wait=False):
        item_id = int(member["item_id"])
        failure = run_closed_member_effects(
            conn,
            item_id=item_id,
            public_ref=str(member["public_ref"]),
            receipt=receipts.get(item_id),
            out=io.StringIO(),
        )
        if failure:
            failed.append(
                f"{member['public_ref']}: its post-close effects did not "
                f"finish: {failure}"
            )
    if not failed:
        return None
    return _settle_refusal(run_id, failed, closed=True)


def settle_members(conn: Any, run_id: str) -> Optional[str]:
    """Close every cleared member together, then run their effects.

    Call after :func:`mark_settling`. A required member is one this run is
    the final delivery of and has completion authority for; while any is
    still at its release wait — its close-out would refuse, or it was never
    cleared — the run may not succeed and no member closes. Returns the
    refusal that keeps the run settling, or ``None`` once it may succeed.
    """
    staged, refusal = _commit_phase(conn, run_id)
    if refusal:
        return refusal
    return _effects_phase(conn, run_id, staged)


__all__ = ["HELD_WITH_RUN", "mark_settling", "settle_members"]
