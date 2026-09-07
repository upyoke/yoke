"""Typed records for the sourced model reference.

Two kinds of number live here and they never mix. ``ApiPrice`` is USD per
million tokens: what a workload would cost billed per token at list price.
``ConsumptionWeight`` is what a subscription plan meters instead — credits,
or whatever unit that plan publishes. A plan's included allowance is not
dollars, no published conversion turns one into the other, and summing them
would invent a figure nobody published, so the two travel in separate fields.

Either kind may be a labelled estimate. An estimate names the exact fields it
covers and states the basis it was reasoned from, so a reader always sees
which numbers came from a source and which someone inferred. The unlabelled
guess is what this shape exists to prevent: unknown stays ``None``, an
inference is labelled, and neither is quietly presented as published.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional

ProposedTier = Literal["tier1", "tier2", "excluded"]
PROPOSED_TIERS: tuple[ProposedTier, ...] = ("tier1", "tier2", "excluded")

#: Every rate an ``ApiPrice`` may carry, and therefore every name its
#: ``estimated_fields`` may label. Readers price from these names too.
PRICE_FIELDS: tuple[str, ...] = (
    "input_per_million_usd",
    "output_per_million_usd",
    "cache_read_per_million_usd",
    "cache_write_per_million_usd",
    "cache_write_long_per_million_usd",
)

#: Every consumption rate a ``ConsumptionWeight`` may carry.
CONSUMPTION_FIELDS: tuple[str, ...] = (
    "input_per_million",
    "cached_input_per_million",
    "output_per_million",
)


@dataclass(frozen=True)
class ApiPrice:
    """API USD per million native tokens. None on a field means unknown."""

    input_per_million_usd: Optional[float] = None
    output_per_million_usd: Optional[float] = None
    cache_read_per_million_usd: Optional[float] = None
    cache_write_per_million_usd: Optional[float] = None
    cache_write_long_per_million_usd: Optional[float] = None
    conditions: Optional[str] = None
    source_url: Optional[str] = None
    checked_at: Optional[str] = None
    effective_at: Optional[str] = None
    #: Rate names above whose value is a reasoned estimate rather than a
    #: published figure. Every other filled rate is what the source states.
    estimated_fields: tuple[str, ...] = ()
    #: Why those estimates are reasonable. Required whenever any is labelled.
    estimate_basis: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkScore:
    """One public benchmark observation. Score stays raw; no composite."""

    name: str
    version: Optional[str] = None
    score: Optional[float] = None
    tested_model: Optional[str] = None
    tested_harness: Optional[str] = None
    tested_reasoning: Optional[str] = None
    source_url: Optional[str] = None
    checked_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConsumptionWeight:
    """What a plan meters per million tokens, in the plan's own unit.

    This is deliberately not money and never becomes money. ``unit`` names
    what the plan publishes — credits, for instance — and the percentage of
    an included allowance those units represent is a separate, usually
    unpublished conversion. A reader that wants dollars reads ``ApiPrice``.
    """

    unit: str
    input_per_million: Optional[float] = None
    cached_input_per_million: Optional[float] = None
    output_per_million: Optional[float] = None
    is_estimate: bool = False
    estimate_basis: Optional[str] = None
    source_url: Optional[str] = None
    checked_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SubscriptionRule:
    """Published subscription consumption rule. Estimates must be labelled."""

    harness: str
    plan: str
    rule: str
    pool: Optional[str] = None
    source_url: Optional[str] = None
    checked_at: Optional[str] = None
    is_estimate: bool = False
    #: Why an estimated rule is reasonable. Required when ``is_estimate``.
    estimate_basis: Optional[str] = None
    #: The plan's own metered weighting, when it publishes one.
    consumption_weight: Optional[ConsumptionWeight] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelRecord:
    """One sourced model. Unknown leaves are None or empty, never invented."""

    model_id: str
    provider: str
    aliases: tuple[str, ...] = ()
    replacement_model_id: Optional[str] = None
    proposed_tier: Optional[ProposedTier] = None
    tier_evidence: Optional[str] = None
    tier_provisional: bool = False
    operator_notes: Optional[str] = None
    api_price: Optional[ApiPrice] = None
    benchmarks: tuple[BenchmarkScore, ...] = ()
    subscription_rules: tuple[SubscriptionRule, ...] = ()
    source_urls: tuple[str, ...] = ()
    checked_at: Optional[str] = None
    display_name: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


@dataclass(frozen=True)
class ModelLookup:
    """Result of looking up a launch model id. Never an exception path."""

    model_id: str
    researched: bool
    record: Optional[ModelRecord] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "researched": self.researched,
            "record": None if self.record is None else self.record.to_dict(),
        }


class ModelReferenceError(ValueError):
    """A proposed record cannot be stored. ``code`` names the recovery."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


__all__ = [
    "ApiPrice",
    "BenchmarkScore",
    "CONSUMPTION_FIELDS",
    "ConsumptionWeight",
    "ModelLookup",
    "ModelRecord",
    "ModelReferenceError",
    "PRICE_FIELDS",
    "PROPOSED_TIERS",
    "ProposedTier",
    "SubscriptionRule",
]
