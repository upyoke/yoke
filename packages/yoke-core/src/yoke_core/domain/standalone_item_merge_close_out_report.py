"""The explicit close-out outcome a standalone merge prints for a person.

The result envelope answers every question a caller can parse, and answered
none an operator could read at a glance. One invocation that closed an item
out — writing the summaries it was handed over the item's execution evidence
and releasing the work claim — looked on the terminal exactly like the four
invocations before it that had only refused: a block of JSON and exit 0. The
run that wrote was indistinguishable from the runs that read.

So every exit names its own outcome on stderr, beside the phase markers,
while stdout stays the machine-readable envelope. Each line is a fact this
run established: the work-claim line is a live holder read rather than the
assumption that a terminal transition released what it usually releases, and
a fact the run never established is left out instead of guessed.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from functools import partial
from typing import Any, Callable, Optional, Sequence

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.public_ref import unresolved_item_ref
from yoke_core.domain import close_out_control_plane_authority as close_out
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id
from yoke_core.domain.standalone_item_merge_evidence import CLOSED_OUT_STATUS

# Every line carries the marker so one grep over a capture answers what a
# merge did, and so the block reads as one outcome rather than loose text.
LINE_PREFIX = "[close-out]"

# This run moved the item to its terminal status.
CLOSED = "closed"
# The item's own record was already terminal before this run reached it.
ALREADY_CLOSED = "already_closed"
# The branch is armed for a queue landing that outlives this command.
LANDING_PENDING = "landing_pending"
# Anything else: a refusal, a merge without close-out, a delivery wait.
NOT_CLOSED = "not_closed"

# The evidence write replaces the item's record with the text this invocation
# supplied, which is the effect an operator most needs named: a close-out run
# as a gate probe replaced a full account of the work with the word "probe".
EVIDENCE_WRITTEN_NOTE = (
    "the --result/--verification text from this run is now the item's record"
)

HOLDER_FUNCTION = "claims.work.holder_get"

# An item the command could not resolve has no public reference to name, and
# the token the caller typed is not one: echoing it in the ref position would
# present whatever was passed — an internal id included — as this item's
# public ref. The blocker still quotes the token inside its own message. The
# phrase itself comes from the one formatter every unresolvable reference
# renders through, so this outcome block reads the same as the rest of the
# product rather than inventing a second wording for the same fact.
UNRESOLVED_REF = unresolved_item_ref()


def _headline(public_ref: str, kind: str, status: str) -> str:
    if kind == CLOSED:
        return f"{public_ref} closed: {status or CLOSED_OUT_STATUS}"
    if kind == ALREADY_CLOSED:
        return (
            f"{public_ref} already closed: {status or CLOSED_OUT_STATUS} "
            "— this run did not close it"
        )
    if kind == LANDING_PENDING:
        return f"{public_ref} not closed: landing pending"
    return f"{public_ref} not closed"


def _evidence_line(recorded: bool, *, from_record: bool) -> str:
    if not recorded:
        return "evidence saved: no"
    if from_record:
        return "evidence saved: recorded before this run"
    return f"evidence saved: yes — {EVIDENCE_WRITTEN_NOTE}"


def _read_claim_state(
    item_id: Any,
    session_id: str,
    dispatch: Callable[..., Any],
) -> str:
    response = dispatch(
        function_id=HOLDER_FUNCTION,
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={},
    )
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        detail = getattr(error, "message", None) or f"{HOLDER_FUNCTION} refused"
        return f"unconfirmed ({detail})"
    result = getattr(response, "result", None)
    if not isinstance(result, Mapping) or "holder" not in result:
        return f"unconfirmed ({HOLDER_FUNCTION} omitted the holder)"
    holder = result.get("holder")
    if holder is None:
        return "released"
    if not isinstance(holder, Mapping):
        return f"unconfirmed ({HOLDER_FUNCTION} returned a malformed holder)"
    holder_session = str(holder.get("session_id") or "")
    caller = session_id or str(resolve_ambient_session_id() or "")
    if holder_session and holder_session == caller:
        return "still held by this session"
    return f"held by session {holder_session or 'unknown'}"


def claim_state(
    item_id: Any,
    session_id: str,
    dispatch: Callable[..., Any],
) -> str:
    """What a live holder read says this run left behind on the item.

    The terminal transition releases the item's work claim inside its own
    transaction, so the release is the control plane's fact to report rather
    than this command's to assume.

    The whole read is contained, not just the call: by the time it runs the
    merge has landed and the item is closed out, so an unreachable relay, a
    holder shape this build does not expect, or an unresolvable ambient
    identity must not raise out of the line whose job is to say the
    close-out succeeded — reporting an outcome cannot become the thing that
    breaks it. Every one of those answers ``unconfirmed``, and nothing is
    ever reported as a release without a holder read that returned none.
    """
    try:
        with close_out.connected_control_plane():
            return _read_claim_state(item_id, session_id, dispatch)
    except Exception as exc:  # noqa: BLE001 - reporting never fails a close-out
        return f"unconfirmed ({exc})"


def outcome_lines(
    envelope: Optional[Mapping[str, Any]] = None,
    *,
    kind: str,
    public_ref: str = "",
    blocker: str = "",
    session_id: str = "",
    dispatch: Optional[Callable[..., Any]] = None,
    evidence_from_record: bool = False,
) -> list[str]:
    """Render the outcome block from what this run actually established."""
    record: Mapping[str, Any] = envelope or {}
    ref = public_ref or str(record.get("public_ref") or UNRESOLVED_REF)
    lines = [_headline(ref, kind, str(record.get("status") or ""))]
    reason = blocker or str(record.get("error") or "")
    if reason:
        lines.append(f"blocker: {reason}")
    pr_number = str(record.get("pr_number") or "")
    if kind == LANDING_PENDING and pr_number:
        lines.append(
            f"pull request #{pr_number} holds the landing; re-run this command "
            "after the landing notice to close the item out"
        )
    recorded = record.get("evidence_recorded")
    if recorded is not None:
        lines.append(_evidence_line(bool(recorded), from_record=evidence_from_record))
    item_id = record.get("item_id")
    if dispatch is not None and item_id is not None:
        lines.append(f"work claim: {claim_state(item_id, session_id, dispatch)}")
    for warning in record.get("warnings") or ():
        lines.append(f"warning: {warning}")
    return [lines[0], *(f"  {line}" for line in lines[1:])]


def print_outcome(
    envelope: Optional[Mapping[str, Any]] = None,
    *,
    kind: str,
    public_ref: str = "",
    blocker: str = "",
    session_id: str = "",
    dispatch: Optional[Callable[..., Any]] = None,
    evidence_from_record: bool = False,
) -> None:
    """Write the outcome block to stderr, beside the phase markers."""
    for line in outcome_lines(
        envelope,
        kind=kind,
        public_ref=public_ref,
        blocker=blocker,
        session_id=session_id,
        dispatch=dispatch,
        evidence_from_record=evidence_from_record,
    ):
        print(f"{LINE_PREFIX} {line}", file=sys.stderr, flush=True)


def bind(
    *,
    session_id: str,
    dispatch: Callable[..., Any],
) -> Callable[..., None]:
    """Bind this run's identity and transport to the outcome printer."""
    return partial(print_outcome, session_id=session_id, dispatch=dispatch)


def final_outcome(
    envelope: Mapping[str, Any],
    *,
    source_status: str,
    skip_status: bool,
) -> tuple[str, str]:
    """The ``(kind, blocker)`` of a merge that reached its own final print.

    Reaching terminal status is not by itself this run's doing: a re-entry
    against an item already ``done`` records its evidence and finds the
    status it wanted, so the headline says which of the two happened.
    """
    status = str(envelope.get("status") or "")
    if status == CLOSED_OUT_STATUS:
        kind = ALREADY_CLOSED if source_status == CLOSED_OUT_STATUS else CLOSED
        return kind, ""
    if skip_status:
        return NOT_CLOSED, (
            "--skip-status was passed: the merge landed and the item's "
            "lifecycle status is unchanged"
        )
    return NOT_CLOSED, (
        f"the merge landed and the item is at {status or 'an unchanged status'}; "
        "close-out finishes when its delivery clears"
    )


__all__: Sequence[str] = (
    "ALREADY_CLOSED",
    "CLOSED",
    "EVIDENCE_WRITTEN_NOTE",
    "HOLDER_FUNCTION",
    "LANDING_PENDING",
    "LINE_PREFIX",
    "NOT_CLOSED",
    "UNRESOLVED_REF",
    "bind",
    "claim_state",
    "final_outcome",
    "outcome_lines",
    "print_outcome",
)
