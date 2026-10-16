"""Who starts a QA case once its deployment stage begins.

Most cases start when their stage does: the stage driver wakes the member's
owner, who runs every case it owes. Some cases can only be judged after real
production traffic exists, such as "a real failed direct wake that a relay
then claimed". Run at stage entry, they fail or prove nothing, so they declare
``wake_path: "manual"`` and a one-line ``wake_evidence`` naming the evidence a
registered read can confirm first. The stage driver does not wake an owner for
them; steering checks the evidence and wakes the owner when it exists.

The method, runner and verdict path are unchanged: a manual case runs exactly
like an automatic one once its owner is woken. The field mirrors
``verdict_path``: it names a path, not a new kind of case.
"""

from __future__ import annotations

from typing import Any

AUTOMATIC = "automatic"
MANUAL = "manual"
WAKE_PATHS = (AUTOMATIC, MANUAL)

#: Longest accepted ``wake_evidence``. One line a report row can carry whole.
WAKE_EVIDENCE_MAX_CHARS = 300

WAKE_PATH_INVALID = "wake_path_invalid"
WAKE_EVIDENCE_REQUIRED = "wake_evidence_required"
WAKE_EVIDENCE_WITHOUT_MANUAL = "wake_evidence_without_manual_wake"
WAKE_EVIDENCE_NOT_ONE_LINE = "wake_evidence_not_one_line"

WAKE_EVIDENCE_GUIDANCE = (
    "name, in one line, the real-traffic evidence that must exist before the "
    "case can run, as something a registered read can confirm (for example "
    "'a deployment run with at least 44 members exists after this release')"
)


class WakePathError(ValueError):
    """A case's wake path or wake evidence is missing or impossible."""


def stored_wake_path(value: Any) -> str:
    """Read a stored wake path; rows written before the field read automatic."""
    return MANUAL if str(value or "") == MANUAL else AUTOMATIC


def _evidence(subject: str, wake_evidence: Any) -> str | None:
    text = str(wake_evidence or "").strip()
    if not text:
        return None
    if "\n" in text or "\r" in text or len(text) > WAKE_EVIDENCE_MAX_CHARS:
        raise WakePathError(
            f"{subject}: {WAKE_EVIDENCE_NOT_ONE_LINE}: wake_evidence must be one "
            f"line of at most {WAKE_EVIDENCE_MAX_CHARS} characters; "
            f"{WAKE_EVIDENCE_GUIDANCE}"
        )
    return text


def validated_wake_path(value: Any, *, subject: str) -> str:
    """One wake path value, refused by name when it is not a known path."""
    declared = AUTOMATIC if value in (None, "") else str(value)
    if declared not in WAKE_PATHS:
        raise WakePathError(
            f"{subject}: {WAKE_PATH_INVALID}: {declared!r} is not a wake path; "
            f"use {AUTOMATIC!r} (starts when its stage begins) or {MANUAL!r} "
            "(starts only when steering wakes its owner)"
        )
    return declared


def validated_wake_evidence(value: Any, *, subject: str) -> str | None:
    """One wake evidence value: one stripped line, or ``None`` when empty."""
    return _evidence(subject, value)


def normalize_wake_path(
    *, case_key: str, wake_path: Any, wake_evidence: Any
) -> tuple[str, str | None]:
    """Return one case's stored ``(wake_path, wake_evidence)``."""
    subject = f"case {case_key!r}"
    declared = validated_wake_path(wake_path, subject=subject)
    evidence = _evidence(subject, wake_evidence)
    if declared == MANUAL and evidence is None:
        raise WakePathError(
            f"{subject}: {WAKE_EVIDENCE_REQUIRED}: wake_path 'manual' needs "
            f"wake_evidence; {WAKE_EVIDENCE_GUIDANCE}"
        )
    if declared == AUTOMATIC and evidence is not None:
        raise WakePathError(
            f"{subject}: {WAKE_EVIDENCE_WITHOUT_MANUAL}: wake_evidence is set "
            "but wake_path is 'automatic', which starts when its stage begins. "
            "Set wake_path to 'manual', or remove wake_evidence."
        )
    return declared, evidence


__all__ = [
    "AUTOMATIC",
    "MANUAL",
    "WAKE_EVIDENCE_GUIDANCE",
    "WAKE_EVIDENCE_MAX_CHARS",
    "WAKE_EVIDENCE_NOT_ONE_LINE",
    "WAKE_EVIDENCE_REQUIRED",
    "WAKE_EVIDENCE_WITHOUT_MANUAL",
    "WAKE_PATHS",
    "WAKE_PATH_INVALID",
    "WakePathError",
    "normalize_wake_path",
    "stored_wake_path",
    "validated_wake_evidence",
    "validated_wake_path",
]
