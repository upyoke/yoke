"""Accepted ``verification_status`` tokens for Dash execution evidence.

The CLI flag and the domain writer that refuses a non-passing value are in
different packages, so the token set lives here: ``--help`` can offer the
choices and the refusal can name them without either side keeping its own
copy.
"""

from __future__ import annotations

from typing import Any

# Every spelling the evidence gate accepts as a passing verification
# outcome. Comparison is case-folded, so callers may pass any casing.
PASSING_VERIFICATION_STATUSES: tuple[str, ...] = (
    "approved", "completed", "passed", "satisfied",
)

DEFAULT_VERIFICATION_STATUS = "passed"


def is_passing(value: object) -> bool:
    """Return whether ``value`` records a passing verification outcome."""
    return str(value).strip().casefold() in PASSING_VERIFICATION_STATUSES


def rejection_message(value: object) -> str:
    """Render the refusal for a non-passing ``verification_status``."""
    return (
        "verification_status must record a passing outcome; "
        f"got {str(value).strip()!r}. Accepted: "
        + ", ".join(PASSING_VERIFICATION_STATUSES)
    )


def status_argument_kwargs() -> dict[str, Any]:
    """Return the ``add_argument`` keywords for ``--verification-status``."""
    return {
        "default": DEFAULT_VERIFICATION_STATUS,
        "choices": PASSING_VERIFICATION_STATUSES,
        "help": (
            "Passing verification outcome recorded on the evidence "
            f"(default: {DEFAULT_VERIFICATION_STATUS}). The gate accepts "
            "only these spellings."
        ),
    }


__all__ = [
    "DEFAULT_VERIFICATION_STATUS",
    "PASSING_VERIFICATION_STATUSES",
    "is_passing",
    "rejection_message",
    "status_argument_kwargs",
]
