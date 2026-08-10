"""Re-prove callable invariants for ledger-present shipped history entries.

Fleet rehearsal already converges pending entries. A ledger-green database
can still hide a historical verification failure: membership alone does not
re-run ``invariants(conn)``. After convergence, every shipped entry that
has ledger membership must pass its callable invariants again on the copy.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Sequence, Tuple


def applied_shipped_names(
    history: Sequence[str],
    pending_names: Callable[[Any, Sequence[str]], Tuple[str, ...]],
    conn: Any,
) -> Tuple[str, ...]:
    """Shipped history entries that currently have ledger membership."""
    pending = set(pending_names(conn, history))
    return tuple(name for name in history if name not in pending)


def verify_applied_history_invariants(
    conn: Any,
    applied: Sequence[str],
    *,
    load_module: Callable[[str], Any],
    redact: str = "",
) -> Optional[str]:
    """Run callable invariants for each applied name; return a fail detail.

    The detail names the failing entry and redacts *redact* (typically the
    copy DSN) so credentials never leave the verdict line.
    """
    for name in applied:
        module = load_module(name)
        invariants = getattr(module, "invariants", None)
        if not callable(invariants):
            continue
        try:
            invariants(conn)
        except BaseException as exc:  # noqa: BLE001 — a verdict, not a crash
            detail = str(exc).strip()
            if redact:
                detail = detail.replace(redact, "<dsn>")
            return f"{name} invariants failed -- {detail}"
    return None


__all__ = [
    "applied_shipped_names",
    "verify_applied_history_invariants",
]
