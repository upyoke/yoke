"""The one-per-work-leg close-out report a worker sends when its work is done.

A retry after a refusal may reword a terminal DONE report. Keying the message
plane's existing idempotency on the sender session, item, and the work claim
the report is sent under makes every deliberate attempt at ONE completion the
same message, so the seat is told once.

The item in that key is the PREFIX-N named in the mandated heading, not
whatever claim the session happens to hold.

The work leg in that key is the claim plus the authorization it answers. A
worker acquires the item claim, works, reports, and releases, so a resume that
reacquires opens a new leg — but a worker held for delivery or a retest keeps
its claim across the resume, and must never release an unfinished lane merely
to make its next report deliverable. What moves in BOTH shapes is the seat's
instruction: the worker acknowledges the message authorizing the new work, and
that acknowledged message is the leg's second half. Retries of one completion
answer the same authorization under the same claim and still collapse into one
message; keying on session and item alone collapsed every later completion into
the first report forever, so the second body was silently discarded.
"""

from __future__ import annotations

from dataclasses import dataclass

from yoke_contracts.public_ref import parse_public_item_ref


#: Namespace for the derived key; a report is one message inside it.
TERMINAL_REPORT_IDEMPOTENCY_PREFIX = "steering-done:"
#: The token the mandated report opens with: ``DONE PREFIX-N <summary>``.
TERMINAL_REPORT_TOKEN = "DONE"
#: Said when a derived key collapses a send whose body differs from the stored
#: one, so a discarded body is never read as a delivered one.
COLLAPSED_DIFFERING_BODY_NOTICE = (
    "Collapsed into an earlier message under the same derived key: the body "
    "you just sent was NOT delivered, and the earlier one still stands. For a "
    "DONE report that earlier body is this work leg's completion, so a "
    "reworded retry owes nothing more — but newly authorized work on the same "
    "item is a new leg: acquire that item's claim again before reporting it, "
    "or the report collapses into this one too."
)


def _first_nonempty_line(body: str) -> str:
    return next((line for line in str(body or "").splitlines() if line.strip()), "")


def is_terminal_done_report(body: str) -> bool:
    """Whether *body* opens with the mandated terminal report token."""
    head = _first_nonempty_line(body).strip().split(maxsplit=1)
    return bool(head) and head[0].rstrip(":").upper() == TERMINAL_REPORT_TOKEN


@dataclass(frozen=True)
class ParsedTerminalReport:
    """A DONE heading, with PREFIX-N when the second token is that form."""

    item_ref: str | None


def parse_terminal_report(body: str) -> ParsedTerminalReport | None:
    """Parse the mandated heading, without scanning later body mentions.

    Returns ``None`` when the body is not a DONE report. A DONE report whose
    second token is not ``PREFIX-N`` has ``item_ref=None`` so the caller can
    refuse instead of guessing another claim.
    """
    parts = _first_nonempty_line(body).strip().split()
    if not parts or parts[0].rstrip(":").upper() != TERMINAL_REPORT_TOKEN:
        return None
    if len(parts) < 2:
        return ParsedTerminalReport(item_ref=None)
    prefix, sequence = parse_public_item_ref(parts[1])
    if prefix is None or sequence is None:
        return ParsedTerminalReport(item_ref=None)
    return ParsedTerminalReport(item_ref=f"{prefix}-{sequence}")


#: Stands in for the authorization half when the sender has acknowledged no
#: instruction at all, so the key shape never varies on its absence.
NO_AUTHORIZATION = "none"


def terminal_report_idempotency_key(
    session_id: str,
    item_id: int,
    claim_id: int,
    authorization_id: str | None = None,
) -> str:
    """Return the key every terminal report of one work leg shares.

    The leg is the sender's claim on the named item plus the last instruction
    it acknowledged. Retries of one completion share both, while a completion
    after a resume differs in at least one — a reacquired claim, a retained
    claim under a newly acknowledged instruction, or both — and reaches the
    seat instead of collapsing into the earlier report.
    """
    return (
        f"{TERMINAL_REPORT_IDEMPOTENCY_PREFIX}{session_id}:"
        f"{int(item_id)}:{int(claim_id)}:"
        f"{authorization_id or NO_AUTHORIZATION}"
    )


__all__ = [
    "COLLAPSED_DIFFERING_BODY_NOTICE",
    "NO_AUTHORIZATION",
    "ParsedTerminalReport",
    "TERMINAL_REPORT_IDEMPOTENCY_PREFIX",
    "TERMINAL_REPORT_TOKEN",
    "is_terminal_done_report",
    "parse_terminal_report",
    "terminal_report_idempotency_key",
]
