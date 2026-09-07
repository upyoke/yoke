"""Which included-usage pool a model bills to, and whether it is empty.

A vendor may split one subscription into several metered pools and bill a
model to exactly one of them. Reading the wrong pool is not a rounding
error: it reports an allowance the launch will never touch, and a policy
that prefers the cheaper pool then moves spend somewhere the operator did
not choose.

So exhaustion here is affirmative only. An unreadable meter, a meter that
covers some other pool, and a meter nobody published are all *unknown*, and
unknown is never exhaustion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from yoke_contracts.session_control.plan_limits import (
    ALL_MODELS_SCOPE,
    cursor_scope_for_model,
)

#: Why a pool is not confirmed exhausted. Each names what to read next.
NO_POOL_WINDOW = "no meter covers this model's pool"
POOL_UNREADABLE = "the pool's meter is unreadable"
POOL_HAS_HEADROOM = "the pool still has headroom"
MODEL_UNNAMED = "no model named, so no pool to match"


@dataclass(frozen=True)
class PoolReading:
    """What the requested model's own billing pool says, and nothing else."""

    #: The vendor's name for the pool, as the meter labels it.
    pool: str | None
    remaining_percent: float | None
    #: True only for an affirmative, readable, pool-matched zero.
    exhausted: bool
    #: Present whenever ``exhausted`` is False, naming why it is not confirmed.
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool": self.pool,
            "remaining_percent": self.remaining_percent,
            "exhausted": self.exhausted,
            "reason": self.reason,
        }


def pool_for_model(surface: str, model: str | None) -> str | None:
    """Name the billing pool a model draws from, when the vendor splits them.

    Cursor is the surface that bills two included pools by model family, and
    it publishes the prefix rule that decides which. Every other surface
    meters by model family name or by the whole account, so the pool is
    whatever its windows say they cover rather than something derivable here.
    """
    value = str(model or "").strip()
    if not value:
        return None
    if surface == "cursor-cli":
        return cursor_scope_for_model(value)
    return None


def window_covers_model(surface: str, model: str | None, scope: str) -> bool:
    """Say whether one meter window covers the model a launch is asking for.

    An account-wide window covers every model. A pooled surface matches on
    the pool. Otherwise the scope names a model family, and it covers the
    model when the model id carries that family name.
    """
    value = str(model or "").strip()
    if not value:
        return False
    if scope == ALL_MODELS_SCOPE:
        return True
    pool = pool_for_model(surface, value)
    if pool is not None:
        return scope == pool
    return scope.strip().lower() in value.lower()


def _matching_window(
    surface: str, model: str | None, windows: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    """Prefer the narrowest window that covers the model.

    A model-scoped meter is the wall that binds first for that model, so it
    outranks the account-wide meter published beside it.
    """
    account_wide: Mapping[str, Any] | None = None
    for window in windows:
        scope = str(window.get("scope") or ALL_MODELS_SCOPE)
        if not window_covers_model(surface, model, scope):
            continue
        if scope == ALL_MODELS_SCOPE:
            if account_wide is None:
                account_wide = window
            continue
        return window
    return account_wide


def pool_exhaustion(
    surface: str,
    model: str | None,
    windows: Sequence[Mapping[str, Any]],
) -> PoolReading:
    """Read the requested model's own pool, never the surface's worst meter.

    The operator-visible failure this prevents: a Cursor Grok launch reported
    against the Other Models pool, which Grok does not bill to, because that
    pool happened to publish the lower number.
    """
    if not str(model or "").strip():
        return PoolReading(None, None, False, MODEL_UNNAMED)
    window = _matching_window(surface, model, windows)
    if window is None:
        return PoolReading(pool_for_model(surface, model), None, False, NO_POOL_WINDOW)
    pool = str(window.get("scope") or ALL_MODELS_SCOPE)
    remaining = window.get("remaining_percent")
    if str(window.get("status") or "unknown") != "ok" or not isinstance(
        remaining, (int, float)
    ):
        return PoolReading(pool, None, False, POOL_UNREADABLE)
    remaining = float(remaining)
    if remaining > 0:
        return PoolReading(pool, remaining, False, POOL_HAS_HEADROOM)
    return PoolReading(pool, remaining, True, None)


__all__ = [
    "MODEL_UNNAMED",
    "NO_POOL_WINDOW",
    "POOL_HAS_HEADROOM",
    "POOL_UNREADABLE",
    "PoolReading",
    "pool_exhaustion",
    "pool_for_model",
    "window_covers_model",
]
