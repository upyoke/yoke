"""Admissibility of a Fleet message body: size, emptiness, and substance.

A durable Fleet message is a coordination fact. It costs the recipient a
delivery, an inbox row, and a hand acknowledgement, so a body that is worthless
a minute after it was written spends coordination machinery on nothing. The
observed failure was a worker forwarding its own watcher output upward: one
steering seat acknowledged roughly thirty messages in an evening whose entire
content was an elapsed-seconds poll, a watcher no-output heartbeat, or a
"still green" liveness note.

``FLEET_SUBSTANTIVE_ONLY_GUIDANCE`` is the rule; this module is the guard that
makes the rule structural on the one path every sender shares. It refuses only
what is unambiguously a progress tick: a short body that carries at least one
progress marker and no substantive signal at all. Anything longer than
``SUBSTANCE_SCAN_LIMIT_CHARS``, and anything naming a failure, a blocker, a
conflict, a decision, or a terminal state, passes untouched — a percentage
inside a real failure report is not a progress tick.
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

# Anything the recipient could act on. One hit is enough to admit the body.
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
)


__all__ = [
    "SUBSTANCE_SCAN_LIMIT_CHARS",
    "is_progress_tick",
    "validate_body",
]


def is_progress_tick(body: str) -> bool:
    """Return True when the body is only progress output with nothing to act on."""
    text = (body or "").strip()
    if not text or len(text) > SUBSTANCE_SCAN_LIMIT_CHARS:
        return False
    if not any(marker.search(text) for marker in _PROGRESS_MARKERS):
        return False
    scanned = _ABSENCE_PHRASES.sub(" ", text)
    return not any(marker.search(scanned) for marker in _SUBSTANTIVE_MARKERS)


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
