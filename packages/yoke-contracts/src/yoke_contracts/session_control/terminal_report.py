"""The one-per-item close-out report a worker sends when its work is done.

A retry after a refusal may reword a terminal DONE report. Keying the message
plane's existing idempotency on the sender session, item, and terminal state
makes every deliberate attempt the same message, so the seat is told once.

The item in that key is the PREFIX-N named in the mandated heading, not
whatever claim the session happens to hold.
"""

from __future__ import annotations

from dataclasses import dataclass

from yoke_contracts.public_ref import parse_public_item_ref


#: Namespace for the derived key; a report is one message inside it.
TERMINAL_REPORT_IDEMPOTENCY_PREFIX = "steering-done:"
#: The token the mandated report opens with: ``DONE PREFIX-N <summary>``.
TERMINAL_REPORT_TOKEN = "DONE"


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


def terminal_report_idempotency_key(session_id: str, item_id: int) -> str:
    """Return the key every terminal report of one session on one item shares."""
    return f"{TERMINAL_REPORT_IDEMPOTENCY_PREFIX}{session_id}:{int(item_id)}"


__all__ = [
    "ParsedTerminalReport",
    "TERMINAL_REPORT_IDEMPOTENCY_PREFIX",
    "TERMINAL_REPORT_TOKEN",
    "is_terminal_done_report",
    "parse_terminal_report",
    "terminal_report_idempotency_key",
]
