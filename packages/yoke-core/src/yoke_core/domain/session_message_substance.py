"""Fleet message-body limits and the automated relay's substance classifier.

Deliberately authored Fleet messages are admissible when non-empty and within
the configured byte limit. :func:`carries_actionable_signal` serves a separate
boundary: machinery uses it to decide whether a turn-end steering report gives
the recipient something to act on before creating durable mail.
"""

from __future__ import annotations

import re

from yoke_core.domain.session_message_types import SessionMessageError


# Phrases that read as a failure word while asserting its absence. Neutralized
# before the substantive scan so "no failures so far" cannot pass as a report
# of a failure.
_ABSENCE_PHRASES = re.compile(
    r"\b(?:no|zero|0|without|not any)\s+"
    r"(?:new\s+)?(?:failures?|errors?|regressions?|breakage|problems?|issues?)\b",
    re.IGNORECASE,
)

# Anything the recipient could act on. One hit is enough to clear the floor.
_SUBSTANTIVE_MARKERS = (
    re.compile(
        r"\b(?:fail|fails|failed|failing|failure|failures|error|errors|red|broke|"
        r"broken|crash|crashed|traceback|regression|defect|bug|timeout|timed out|"
        r"abort|aborted|refused|refuses|denied|deny|conflict|conflicts|blocked|"
        r"blocker|blocking|stuck|stalled|cannot|can't|unable|missing|wrong|"
        r"unexpected|mismatch)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:decide|decision|approve|approval|question|escalate|escalation|"
        r"need|needs|needed|help|advice|confirm|clarify|permission)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:done|complete|completed|finished|merged|landed|shipped|deployed|"
        r"released|cancelled|canceled|abandoned|handoff|handing off)\b",
        re.IGNORECASE,
    ),
    # A directive or a go-signal: the recipient is being told to act, or
    # told the work it was waiting on is now theirs to move.
    re.compile(
        r"\b(?:go|proceed|resume|unblocked|parked|paused|handing over)\b",
        re.IGNORECASE,
    ),
    # A question is a decision the recipient owns, whatever words carry it.
    re.compile(r"\?"),
)


__all__ = [
    "carries_actionable_signal",
    "validate_body",
]


def carries_actionable_signal(body: str) -> bool:
    """Return True when the body names something the recipient could act on.

    The floor: a failure, a blocker, a conflict, a decision, a question, or a
    terminal outcome. A body clearing nothing here is a bare status verb, a
    wait, a progress count, or a self-check note — true when it was written
    and worthless a minute later.
    """
    text = (body or "").strip()
    if not text:
        return False
    scanned = _ABSENCE_PHRASES.sub(" ", text)
    return any(marker.search(scanned) for marker in _SUBSTANTIVE_MARKERS)


def validate_body(body: str, *, max_body_bytes: int) -> None:
    """Require a non-empty body within the configured byte limit."""
    body_bytes = len(body.encode("utf-8"))
    if body_bytes == 0:
        raise SessionMessageError("body_empty", "message body must not be empty")
    if body_bytes > max_body_bytes:
        raise SessionMessageError(
            "body_too_large",
            f"message body is {body_bytes} bytes; maximum is {max_body_bytes}",
            jsonpath="$.payload.body",
        )
