"""Re-prove callable invariants for ledger-present shipped history entries.

Fleet rehearsal already converges pending entries. A ledger-green database
can still hide a historical verification failure: membership alone does not
re-run ``invariants(conn)``. After convergence, every shipped entry that
has ledger membership must pass its callable invariants again on the copy.

Re-proving against a live copy is what makes an entry's invariants a claim
about the schema rather than about the rows: whatever the apply left behind,
live builds have been writing since, and an entry that asserted a row count
is re-judged here against traffic it never saw.
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
    history: Sequence[str],
    load_module: Callable[[str], Any],
    redact: str = "",
) -> Optional[str]:
    """Run callable invariants for each applied name; return a fail detail.

    Every shipped module is loaded before verification so a pending entry can
    retire an applied predecessor's invariants before convergence applies the
    retiring entry. ``RETIRES_INVARIANTS`` names prior history entries whose
    claims no longer stand — the surface they describe is gone from the final
    schema, or what they asserted was never an invariant.

    The detail names the failing entry and redacts *redact* (typically the
    copy DSN) so credentials never leave the verdict line.
    """
    modules = {name: load_module(name) for name in history}
    retired = {
        retired_name
        for module in modules.values()
        for retired_name in getattr(module, "RETIRES_INVARIANTS", ())
    }
    for name in applied:
        if name in retired:
            continue
        module = modules[name]
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
