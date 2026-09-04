"""The one-per-item close-out report a worker sends when its work is done.

A retry after a refusal may reword a terminal DONE report. Keying the message
plane's existing idempotency on the sender session, item, and terminal state
makes every deliberate attempt the same message, so the seat is told once.
"""

from __future__ import annotations


#: Namespace for the derived key; a report is one message inside it.
TERMINAL_REPORT_IDEMPOTENCY_PREFIX = "steering-done:"
#: The token the mandated report opens with: ``DONE PREFIX-N <summary>``.
TERMINAL_REPORT_TOKEN = "DONE"


def is_terminal_done_report(body: str) -> bool:
    """Whether *body* opens with the mandated terminal report token."""
    first_line = next(
        (line for line in str(body or "").splitlines() if line.strip()), ""
    )
    head = first_line.strip().split(maxsplit=1)
    return bool(head) and head[0].rstrip(":").upper() == TERMINAL_REPORT_TOKEN


def terminal_report_idempotency_key(session_id: str, item_id: int) -> str:
    """Return the key every terminal report of one session on one item shares."""
    return f"{TERMINAL_REPORT_IDEMPOTENCY_PREFIX}{session_id}:{int(item_id)}"


__all__ = [
    "TERMINAL_REPORT_IDEMPOTENCY_PREFIX",
    "TERMINAL_REPORT_TOKEN",
    "is_terminal_done_report",
    "terminal_report_idempotency_key",
]
