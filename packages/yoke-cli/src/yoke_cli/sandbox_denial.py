"""Translate a harness approval or sandbox refusal into a named recovery.

A harness that has not been given the unattended posture reports a blocked
control-plane call as ``Operation not permitted`` somewhere inside a
connection error. That text names the syscall, not the boundary, so an agent
reads it as a broken database and starts debugging Postgres — or asks its
operator to approve the command, one command at a time, including the
field-note command it is told to reach for when something goes wrong.

Wrapping the adapter here means every registered ``yoke`` command teaches the
same one-line fix, and the harness is identified from the process tree rather
than assumed, so the recovery named is the one that applies.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, List, Optional, Sequence

from yoke_contracts.harness_family_identity import nearest_harness_family
from yoke_contracts.harness_unattended_posture import sandbox_recovery

# Substrings an OS-level refusal carries once it surfaces as a connection or
# write failure. Deliberately narrow: a permission error is the signal, and a
# wider net would relabel ordinary authentication failures as sandbox ones.
DENIAL_MARKERS = ("operation not permitted", "permission denied")


def _operation(argv: Sequence[str]) -> str:
    """Name the invocation compactly: the command, not its whole argument list."""
    words = [token for token in list(argv)[:3] if not token.startswith("-")]
    return " ".join(["yoke", *words]) if words else "yoke"


def diagnose(exc: BaseException, argv: Sequence[str]) -> Optional[str]:
    """Return the refusal text for a harness denial, or ``None`` otherwise."""
    try:
        detail = str(exc)
        if not any(marker in detail.lower() for marker in DENIAL_MARKERS):
            return None
        recovery = sandbox_recovery(nearest_harness_family())
        if not recovery:
            return None
        return f"yoke: {_operation(argv)} was refused: {detail.strip()}\n{recovery}"
    except Exception:  # noqa: BLE001 — diagnosis must never mask the real error
        return None


def run(
    adapter: Callable[[List[str]], Any],
    remaining: List[str],
    argv: Sequence[str],
) -> Any:
    """Run *adapter*, re-raising anything that is not a harness denial."""
    try:
        return adapter(remaining)
    except Exception as exc:  # noqa: BLE001 — re-raised unless it is a denial
        message = diagnose(exc, argv)
        if message is None:
            raise
        print(message, file=sys.stderr)
        return 1


__all__ = ["DENIAL_MARKERS", "diagnose", "run"]
