"""Admissibility of a Fleet message body: size, emptiness, and substance.

A durable Fleet message is a coordination fact. It costs the recipient a
delivery, an inbox row, and a hand acknowledgement, so a body that is worthless
a minute after it was written spends coordination machinery on nothing. The
observed failure was a worker forwarding its own watcher output upward: one
steering seat acknowledged roughly thirty messages in an evening whose entire
content was an elapsed-seconds poll, a watcher no-output heartbeat, or a
"still green" liveness note.

``FLEET_SUBSTANTIVE_ONLY_GUIDANCE`` is the rule. Two predicates enforce it at
two different strengths, over one shared notion of what the recipient could
act on:

- :func:`carries_actionable_signal` is the floor. A body naming a failure, a
  blocker, a conflict, a decision, a question, or a terminal outcome clears
  it; a bare status verb, a wait, a progress count, or a self-check note does
  not. The turn-end steering relay applies the floor to a Stop body, because
  that body is mailed by the machinery rather than chosen by a sender.
- :func:`is_progress_tick` is the narrower classifier the send path refuses
  on: a short body that carries a progress marker and clears nothing on the
  floor. A sender who wrote the words gets refused only for what is
  unambiguously a progress tick, so ``yoke say`` still carries a deliberate
  status line. Anything longer than ``SUBSTANCE_SCAN_LIMIT_CHARS``, and
  anything actionable, passes untouched — a percentage inside a real failure
  report is not a progress tick.
"""

from __future__ import annotations

import re

from yoke_contracts.session_control.teaching import (
    FLEET_SUBSTANTIVE_ONLY_GUIDANCE,
)
from yoke_core.domain.session_message_types import SessionMessageError


SUBSTANCE_SCAN_LIMIT_CHARS = 240

# Phrases that read as a failure word while asserting its absence. Neutralized
# before the substantive scan so "no failures so far" cannot pass as a report
# of a failure.
_ABSENCE_PHRASES = re.compile(
    r"\b(?:no|zero|0|without|not any)\s+"
    r"(?:new\s+)?(?:failures?|errors?|regressions?|breakage|problems?|issues?)\b",
    re.IGNORECASE,
)

# Output a watcher, a test runner, or a poll loop produces about its own
# liveness. None of it changes what the recipient would do.
_PROGRESS_MARKERS = (
    re.compile(r"^\s*#?\s*workflow status\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\bno progress for\s+\d+", re.IGNORECASE),
    re.compile(r"\bwaiting_on\s*=", re.IGNORECASE),
    re.compile(r"\belapsed\s*[:=]\s*\d+", re.IGNORECASE),
    re.compile(r"\bnext poll\b", re.IGNORECASE),
    re.compile(r"\bsuppressed\s+\d+\s+ticks?\b", re.IGNORECASE),
    re.compile(r"\d{1,3}\s?%"),
    re.compile(
        r"\bstill\s+(?:green|running|going|passing|good|fine|ok)\b", re.IGNORECASE
    ),
    re.compile(r"\bso far\b", re.IGNORECASE),
    re.compile(r"\b(?:progress|passing|green)\s+dots\b", re.IGNORECASE),
    re.compile(r"\bstreaming\b", re.IGNORECASE),
    re.compile(r"\bheartbeat\b", re.IGNORECASE),
    re.compile(r"\bin_progress\b", re.IGNORECASE),
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
    "SUBSTANCE_SCAN_LIMIT_CHARS",
    "carries_actionable_signal",
    "is_progress_tick",
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


def is_progress_tick(body: str) -> bool:
    """Return True when the body is only progress output with nothing to act on."""
    text = (body or "").strip()
    if not text or len(text) > SUBSTANCE_SCAN_LIMIT_CHARS:
        return False
    if not any(marker.search(text) for marker in _PROGRESS_MARKERS):
        return False
    return not carries_actionable_signal(text)


def validate_body(body: str, *, max_body_bytes: int) -> None:
    """Raise ``SessionMessageError`` unless the body is admissible as a message."""
    body_bytes = len(body.encode("utf-8"))
    if body_bytes == 0:
        raise SessionMessageError("body_empty", "message body must not be empty")
    if body_bytes > max_body_bytes:
        raise SessionMessageError(
            "body_too_large",
            f"message body is {body_bytes} bytes; maximum is {max_body_bytes}",
            jsonpath="$.payload.body",
        )
    if is_progress_tick(body):
        raise SessionMessageError(
            "body_not_substantive",
            "message body is progress output, not a substantive update; it was "
            f"not sent. {FLEET_SUBSTANTIVE_ONLY_GUIDANCE} Relay this line in "
            "your own output instead, and send a message when there is "
            "something for the recipient to act on.",
            jsonpath="$.payload.body",
        )
