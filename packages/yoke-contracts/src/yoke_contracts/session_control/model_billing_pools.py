"""Which included-usage pool a model bills to, and whether it can still run.

A vendor may split one subscription into several metered pools and bill a
model to exactly one of them. Reading the wrong pool is not a rounding
error: it reports an allowance the launch will never touch, and a policy
that prefers the cheaper pool then moves spend somewhere the operator did
not choose.

So exhaustion here is affirmative only. An unreadable meter, a meter that
covers some other pool, and a meter nobody published are all *unknown*, and
unknown is never exhaustion.

An empty included pool is still not exhaustion when the provider bills past
it. Paid extra usage (see :mod:`yoke_contracts.session_control.extra_usage`)
is account-wide, so it applies to whichever pool the model bills to. A pool
is exhausted only when its included window is an affirmative zero AND a fresh
extra-usage reading affirmatively says the provider will not bill past it:
disabled, cap reached, or no funds. Unknown, unsupported and stale extra
usage leave the launch to the provider, whose own refusal stays authoritative.

This is the one availability answer. Launch placement, launch previews,
native wakes, session status and the steering report all read it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from yoke_contracts.session_control.extra_usage import (
    EXTRA_AVAILABLE,
    EXTRA_BLOCKING_STATUSES,
    EXTRA_STALE,
    EXTRA_UNKNOWN,
    extra_usage_label,
    sanitize_extra_usage,
)
from yoke_contracts.session_control.plan_limits import (
    ALL_MODELS_SCOPE,
    PLAN_LIMIT_FRESH_SECONDS,
    cursor_scope_for_model,
)
from yoke_contracts.timestamps import parse_instant

#: Why a pool is not confirmed exhausted. Each names what to read next.
NO_POOL_WINDOW = "no meter covers this model's pool"
POOL_UNREADABLE = "the pool's meter is unreadable"
POOL_HAS_HEADROOM = "the pool still has headroom"
MODEL_UNNAMED = "no model named, so no pool to match"
EXTRA_USAGE_PERMITS = "the included pool is empty; extra usage permits work"
EXTRA_USAGE_UNPROVEN = (
    "the included pool is empty; extra usage is not proven blocked, so the "
    "provider decides"
)


@dataclass(frozen=True)
class PoolReading:
    """What the requested model's own billing pool says, and nothing else."""

    #: The vendor's name for the pool, as the meter labels it.
    pool: str | None
    remaining_percent: float | None
    #: True only for a readable, pool-matched included zero that fresh
    #: extra usage affirmatively cannot cover.
    exhausted: bool
    #: Present whenever ``exhausted`` is False, naming why it is not confirmed.
    reason: str | None
    #: True for an affirmative, readable, pool-matched included zero.
    included_empty: bool = False
    #: Extra-usage status as of now: a stored status, or ``stale``.
    extra_status: str = EXTRA_UNKNOWN
    #: The shared phrase naming the extra-usage facts.
    extra_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool": self.pool,
            "remaining_percent": self.remaining_percent,
            "exhausted": self.exhausted,
            "reason": self.reason,
            "included_empty": self.included_empty,
            "extra_status": self.extra_status,
            "extra_label": self.extra_label,
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


def extra_usage_status(
    extra: Mapping[str, Any] | None,
    *,
    observed_at: datetime | str | None,
    now: datetime | str,
) -> str:
    """The stored status, or ``stale`` once the reading is too old to prove it.

    A connected relay refreshes every four minutes, so a reading past the
    display cutoff means the refresh has not landed; until it does, the old
    answer proves nothing about the account now.
    """
    status = sanitize_extra_usage(extra)["status"]
    if observed_at is None:
        return EXTRA_STALE
    age = (parse_instant(now) - parse_instant(observed_at)).total_seconds()
    if age > PLAN_LIMIT_FRESH_SECONDS:
        return EXTRA_STALE
    return status


def included_zero_blocks(
    extra: Mapping[str, Any] | None,
    *,
    observed_at: datetime | str | None,
    now: datetime | str,
) -> bool:
    """True when an empty included window really stops work on this surface."""
    status = extra_usage_status(extra, observed_at=observed_at, now=now)
    return status in EXTRA_BLOCKING_STATUSES


def pool_exhaustion(
    surface: str,
    model: str | None,
    windows: Sequence[Mapping[str, Any]],
    *,
    extra_usage: Mapping[str, Any] | None,
    observed_at: datetime | str | None,
    now: datetime | str,
) -> PoolReading:
    """Read the requested model's own pool, never the surface's worst meter.

    The operator-visible failure this prevents: a Cursor Grok launch reported
    against the Other Models pool, which Grok does not bill to, because that
    pool happened to publish the lower number.
    """
    status = extra_usage_status(extra_usage, observed_at=observed_at, now=now)
    extra = {
        "extra_status": status,
        "extra_label": extra_usage_label(sanitize_extra_usage(extra_usage), status),
    }
    if not str(model or "").strip():
        return PoolReading(None, None, False, MODEL_UNNAMED, **extra)
    window = _matching_window(surface, model, windows)
    if window is None:
        return PoolReading(
            pool_for_model(surface, model), None, False, NO_POOL_WINDOW, **extra
        )
    pool = str(window.get("scope") or ALL_MODELS_SCOPE)
    remaining = window.get("remaining_percent")
    if str(window.get("status") or "unknown") != "ok" or not isinstance(
        remaining, (int, float)
    ):
        return PoolReading(pool, None, False, POOL_UNREADABLE, **extra)
    remaining = float(remaining)
    if remaining > 0:
        return PoolReading(pool, remaining, False, POOL_HAS_HEADROOM, **extra)
    if status in EXTRA_BLOCKING_STATUSES:
        return PoolReading(pool, remaining, True, None, True, **extra)
    reason = EXTRA_USAGE_PERMITS if status == EXTRA_AVAILABLE else EXTRA_USAGE_UNPROVEN
    return PoolReading(pool, remaining, False, reason, True, **extra)


__all__ = [
    "EXTRA_USAGE_PERMITS",
    "EXTRA_USAGE_UNPROVEN",
    "MODEL_UNNAMED",
    "NO_POOL_WINDOW",
    "POOL_HAS_HEADROOM",
    "POOL_UNREADABLE",
    "PoolReading",
    "extra_usage_status",
    "included_zero_blocks",
    "pool_exhaustion",
    "pool_for_model",
    "window_covers_model",
]
