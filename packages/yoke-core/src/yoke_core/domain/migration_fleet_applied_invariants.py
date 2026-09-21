"""Re-prove callable invariants for ledger-present shipped history entries.

Fleet rehearsal already converges pending entries. A ledger-green database
can still hide a historical verification failure: membership alone does not
re-run ``invariants(conn)``. After convergence, every shipped entry that
has ledger membership must pass its callable invariants again on the copy.

Re-proving against a live copy is what makes an entry's invariants a claim
about the schema rather than about the rows: whatever the apply left behind,
live builds have been writing since, and an entry that asserted a row count
is re-judged here against traffic it never saw.

A standing invariant that cannot evaluate is a third answer, not a pass.
The fleet summary reports it beside passed and failed, with the reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Tuple


RETIRED_STANDING_INVARIANTS: dict[str, str] = {
    # 0035's apply still clears a latch no closed checklist backs. The live
    # run_onboard signal later also latches a deployment-superseded run, so
    # the frozen invariants() cannot evaluate on those databases. The
    # standing claim is obsolete; the module bytes stay frozen.
    "0035_clear_unproven_onboard_activation_latch": (
        "the live run_onboard signal also latches a deployment-superseded "
        "run, while this entry recognizes only a fully closed checklist"
    ),
}


@dataclass(frozen=True)
class AppliedInvariantReport:
    """Failure detail, or the standing invariants that declined to evaluate."""

    failure: Optional[str] = None
    skipped: Tuple[Tuple[str, str], ...] = ()


def applied_shipped_names(
    history: Sequence[str],
    pending_names: Callable[[Any, Sequence[str]], Tuple[str, ...]],
    conn: Any,
) -> Tuple[str, ...]:
    """Shipped history entries that currently have ledger membership."""
    pending = set(pending_names(conn, history))
    return tuple(name for name in history if name not in pending)


def skipped_standing_invariant_line(name: str, reason: str) -> str:
    """One summary/stream line for a standing invariant that did not evaluate."""
    return f"skipped {name} -- {reason}"


def format_fleet_summary(verdicts: Sequence[Any]) -> str:
    """Passed, failed, and skipped standing invariants for one fleet run.

    Database verdicts stay the pass/fail counts. Distinct retired standing
    invariants are the third count, each named with its reason so a reader
    who is not following a converge stream still sees them.
    """
    failed = [verdict for verdict in verdicts if not verdict.passed]
    skipped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for verdict in verdicts:
        for name, reason in getattr(verdict, "skipped_invariants", ()):
            if name in seen:
                continue
            seen.add(name)
            skipped.append((name, reason))
    lines = [
        f"{len(verdicts) - len(failed)} passed, {len(failed)} failed, "
        f"{len(skipped)} skipped"
    ]
    lines.extend(
        skipped_standing_invariant_line(name, reason)
        for name, reason in skipped
    )
    return "\n".join(lines)


def verify_applied_history_invariants(
    conn: Any,
    applied: Sequence[str],
    *,
    history: Sequence[str],
    load_module: Callable[[str], Any],
    redact: str = "",
) -> AppliedInvariantReport:
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
    skipped: list[tuple[str, str]] = []
    for name in applied:
        retired_reason = RETIRED_STANDING_INVARIANTS.get(name)
        if retired_reason is not None:
            skipped.append((name, retired_reason))
            print(
                f"converging {name}: standing invariant skipped -- "
                f"{retired_reason}"
            )
            continue
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
            return AppliedInvariantReport(
                failure=f"{name} invariants failed -- {detail}",
                skipped=tuple(skipped),
            )
    return AppliedInvariantReport(skipped=tuple(skipped))


__all__ = [
    "AppliedInvariantReport",
    "RETIRED_STANDING_INVARIANTS",
    "applied_shipped_names",
    "format_fleet_summary",
    "skipped_standing_invariant_line",
    "verify_applied_history_invariants",
]
