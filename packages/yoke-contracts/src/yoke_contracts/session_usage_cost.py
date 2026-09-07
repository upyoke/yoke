"""What a session's recorded tokens would have cost at API list prices.

This is an *estimate of API-equivalent spend*, and the wording is load
bearing. A session run under a subscription plan spends that plan's own
meters — Cursor's model pools, Codex's rate-limit windows, Claude's plan
allowance — and no published conversion turns those meters into dollars.
The number here answers a different question: what the same tokens would
have cost had they been billed per token at list price. It is never
presented as plan consumption, and it never replaces the native pool
meters those harnesses report for themselves.

Prices come from the shared model reference and nowhere else. There is no
price table here, no fallback rate, and no "close enough" default: an
unknown model or an unpriced bucket produces a partial or unavailable
cost that names what is missing, because a confidently wrong dollar
figure is worse than an honest gap. Raw token capture never depends on
any of this — a session records what it consumed whether or not anyone
has ever researched its price.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from yoke_contracts.session_usage_facts import (
    USAGE_BUCKETS,
    USAGE_COMPLETE,
    ModelUsage,
    SessionUsage,
)


#: Each billable bucket beside the reference price field that rates it.
#: ``cache_write_long`` covers writes a provider bills at a longer cache
#: lifetime; a reference that publishes no separate long-TTL rate leaves
#: that field absent and the bucket priced from the ordinary cache-write
#: rate, which the resulting cost reports as an approximation.
BUCKET_PRICE_FIELDS: Mapping[str, str] = {
    "input": "input_per_million_usd",
    "cached_input": "cache_read_per_million_usd",
    "cache_write": "cache_write_per_million_usd",
    "cache_write_long": "cache_write_long_per_million_usd",
    "output": "output_per_million_usd",
}

#: The rate a long-TTL cache write falls back to when the reference
#: publishes only one cache-write price. Substituting it is stated on the
#: cost rather than hidden, because the two rates genuinely differ.
LONG_CACHE_WRITE_FALLBACK = "cache_write"

TOKENS_PER_PRICE_UNIT = 1_000_000

#: Every bucket carrying tokens had a published price.
COST_COMPLETE = "complete"
#: Some tokens were priced and some were not, or a substitute rate was used.
COST_PARTIAL = "partial"
#: Nothing could be priced — no reference, no researched model, no rates.
COST_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SessionCost:
    """An API-equivalent estimate, with what it could not price named."""

    usd: float = 0.0
    status: str = COST_UNAVAILABLE
    reason: str = ""
    #: Where the rates came from, as the reference states it.
    price_basis: str = ""
    #: When those rates were last checked, as the reference states it.
    effective_date: str = ""

    def priced(self) -> bool:
        """True when at least some tokens were converted to dollars."""
        return self.status != COST_UNAVAILABLE


def session_cost(
    usage: Optional[SessionUsage],
    prices_for_model: Callable[[str], Optional[object]],
) -> SessionCost:
    """Price one session's recorded usage, naming every gap it hits.

    ``prices_for_model`` returns the reference's price record for a served
    model id, or ``None`` when that model is unknown to it. Taking the
    lookup as an argument keeps this calculation testable against fixed
    rates and keeps the reference a caller's concern rather than an
    import this module depends on.
    """
    if usage is None or not usage.models:
        return SessionCost(reason="no usage recorded for this session")
    total = 0.0
    gaps: list[str] = []
    bases: list[str] = []
    dates: list[str] = []
    priced_any = False
    for entry in usage.models:
        prices = prices_for_model(entry.model)
        if prices is None:
            gaps.append(f"no researched price for {entry.model}")
            continue
        amount, missing, approximated = _model_cost(entry, prices)
        if amount is None:
            gaps.append(f"no priced tokens for {entry.model}")
            continue
        priced_any = True
        total += amount
        gaps.extend(f"{bucket} price unknown for {entry.model}" for bucket in missing)
        if approximated:
            gaps.append(
                f"long-lifetime cache writes for {entry.model} priced at the "
                "ordinary cache-write rate"
            )
        _collect(bases, _text(prices, "source_url"), _text(prices, "conditions"))
        _collect(dates, _text(prices, "checked_at"))
    if not priced_any:
        return SessionCost(reason="; ".join(gaps) or "no prices available")
    complete = not gaps and usage.status == USAGE_COMPLETE
    return SessionCost(
        usd=total,
        status=COST_COMPLETE if complete else COST_PARTIAL,
        reason="" if complete else "; ".join(gaps or [usage.reason]),
        price_basis=" · ".join(bases),
        effective_date=min(dates) if dates else "",
    )


def _model_cost(
    entry: ModelUsage, prices: object
) -> tuple[Optional[float], list[str], bool]:
    """Return one model's cost, the buckets it could not price, and whether
    a long-lifetime cache-write rate was substituted."""
    total = 0.0
    missing: list[str] = []
    approximated = False
    counted = False
    for bucket in USAGE_BUCKETS:
        tokens = getattr(entry, bucket)
        if tokens <= 0:
            continue
        rate = _rate(prices, BUCKET_PRICE_FIELDS[bucket])
        if rate is None and bucket == "cache_write_long":
            rate = _rate(prices, BUCKET_PRICE_FIELDS[LONG_CACHE_WRITE_FALLBACK])
            approximated = rate is not None
        if rate is None:
            missing.append(bucket)
            continue
        total += tokens * rate / TOKENS_PER_PRICE_UNIT
        counted = True
    return (total if counted else None), missing, approximated


def _rate(prices: object, field: str) -> Optional[float]:
    """Read one published per-million rate, or ``None`` when unpublished."""
    value = getattr(prices, field, None)
    if isinstance(value, bool) or value is None:
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    return rate if rate >= 0 else None


def _text(prices: object, field: str) -> str:
    value = getattr(prices, field, "")
    return value.strip() if isinstance(value, str) else ""


def _collect(target: list[str], *values: str) -> None:
    """Keep each distinct non-empty value once, in first-seen order."""
    for value in values:
        if value and value not in target:
            target.append(value)


__all__ = [
    "BUCKET_PRICE_FIELDS",
    "COST_COMPLETE",
    "COST_PARTIAL",
    "COST_UNAVAILABLE",
    "LONG_CACHE_WRITE_FALLBACK",
    "TOKENS_PER_PRICE_UNIT",
    "SessionCost",
    "session_cost",
]
