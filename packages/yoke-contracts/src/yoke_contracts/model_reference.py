"""Sourced model reference shared by steering, cost readers, and refresh.

The durable store is this package: typed records plus a seeded document.
Lookup never raises. ``researched=False`` is the explicit not-researched
marker — missing facts are not a discovery, launch, or usage gate.
Researched ``proposed_tier`` is not operator routing; per-surface routing
lives with the steering selection policy, not this reference.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Literal, Mapping, Optional

from yoke_contracts.session_model_facts import (
    CLAUDE_CONTEXT_TIER_SUFFIX,
    REASONING_EFFORT_VALUES,
)

ProposedTier = Literal["tier1", "tier2", "excluded"]
PROPOSED_TIERS: tuple[ProposedTier, ...] = ("tier1", "tier2", "excluded")


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
class SubscriptionRule:
    """Published subscription consumption rule. Estimates must be labelled."""

    harness: str
    plan: str
    rule: str
    pool: Optional[str] = None
    source_url: Optional[str] = None
    checked_at: Optional[str] = None
    is_estimate: bool = False

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


def lookup_stem(model_id: str) -> str:
    """Strip selector encoding so a launch id hits its canonical record."""
    token = str(model_id or "").strip()
    if "[" in token and token.endswith("]"):
        token = token[: token.index("[")]
    if token.lower().endswith(CLAUDE_CONTEXT_TIER_SUFFIX):
        token = token[: -len(CLAUDE_CONTEXT_TIER_SUFFIX)]
    token = token.removesuffix("-fast")
    for level in sorted(REASONING_EFFORT_VALUES, key=len, reverse=True):
        suffix = f"-{level}"
        if token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _index_records(records: Iterable[ModelRecord]) -> dict[str, ModelRecord]:
    indexed: dict[str, ModelRecord] = {}
    for record in records:
        for key in (record.model_id, *record.aliases):
            indexed[key] = record
            stem = lookup_stem(key)
            indexed.setdefault(stem, record)
    return indexed


def _records() -> tuple[ModelRecord, ...]:
    from yoke_contracts.model_reference_data import MODEL_RECORDS

    return MODEL_RECORDS


def iter_model_records() -> tuple[ModelRecord, ...]:
    """Return the seeded reference document."""
    return _records()


def lookup_model_reference(model_id: str) -> ModelLookup:
    """Look up a launch ``--model`` string. Unknown → researched=False."""
    asked = str(model_id or "").strip()
    if not asked:
        return ModelLookup(model_id="", researched=False)
    indexed = _index_records(_records())
    record = indexed.get(asked) or indexed.get(lookup_stem(asked))
    if record is None:
        return ModelLookup(model_id=asked, researched=False)
    return ModelLookup(model_id=asked, researched=True, record=record)


def lookup_api_price(model_id: str) -> Optional[ApiPrice]:
    """Return API price for cost readers. None when unknown or not researched."""
    lookup = lookup_model_reference(model_id)
    if not lookup.researched or lookup.record is None:
        return None
    return lookup.record.api_price


def _optional_float(value: object, field: str) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ModelReferenceError("price_invalid", f"{field} must be a number or null")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ModelReferenceError(
            "price_invalid", f"{field} must be a number or null"
        ) from exc


def _optional_str(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _tuple_of_str(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if not isinstance(value, (list, tuple)):
        raise ModelReferenceError("record_invalid", f"{field} must be a list of strings")
    return tuple(str(item).strip() for item in value if str(item).strip())


def validate_model_record(payload: Mapping[str, Any]) -> ModelRecord:
    """Rebuild one record from JSON. Named refusal, never a traceback."""
    model_id = str(payload.get("model_id") or "").strip()
    provider = str(payload.get("provider") or "").strip()
    if not model_id or not provider:
        raise ModelReferenceError(
            "record_invalid",
            "model_id and provider are required; fill unknown leaves with null",
        )
    tier = payload.get("proposed_tier")
    if tier is not None and tier not in PROPOSED_TIERS:
        raise ModelReferenceError(
            "tier_invalid",
            f"proposed_tier must be one of {', '.join(PROPOSED_TIERS)} or null",
        )
    price_raw = payload.get("api_price")
    price = None
    if isinstance(price_raw, Mapping):
        price = ApiPrice(
            input_per_million_usd=_optional_float(
                price_raw.get("input_per_million_usd"), "input_per_million_usd"
            ),
            output_per_million_usd=_optional_float(
                price_raw.get("output_per_million_usd"), "output_per_million_usd"
            ),
            cache_read_per_million_usd=_optional_float(
                price_raw.get("cache_read_per_million_usd"),
                "cache_read_per_million_usd",
            ),
            cache_write_per_million_usd=_optional_float(
                price_raw.get("cache_write_per_million_usd"),
                "cache_write_per_million_usd",
            ),
            cache_write_long_per_million_usd=_optional_float(
                price_raw.get("cache_write_long_per_million_usd"),
                "cache_write_long_per_million_usd",
            ),
            conditions=_optional_str(price_raw.get("conditions")),
            source_url=_optional_str(price_raw.get("source_url")),
            checked_at=_optional_str(price_raw.get("checked_at")),
            effective_at=_optional_str(price_raw.get("effective_at")),
        )
    elif price_raw is not None:
        raise ModelReferenceError("price_invalid", "api_price must be an object or null")
    benchmarks = []
    for raw in payload.get("benchmarks") or ():
        if not isinstance(raw, Mapping) or not str(raw.get("name") or "").strip():
            raise ModelReferenceError("benchmark_invalid", "each benchmark needs a name")
        score = raw.get("score")
        parsed_score = None if score is None else _optional_float(score, "score")
        benchmarks.append(
            BenchmarkScore(
                name=str(raw.get("name")).strip(),
                version=_optional_str(raw.get("version")),
                score=parsed_score,
                tested_model=_optional_str(raw.get("tested_model")),
                tested_harness=_optional_str(raw.get("tested_harness")),
                tested_reasoning=_optional_str(raw.get("tested_reasoning")),
                source_url=_optional_str(raw.get("source_url")),
                checked_at=_optional_str(raw.get("checked_at")),
            )
        )
    rules = []
    for raw in payload.get("subscription_rules") or ():
        if not isinstance(raw, Mapping):
            raise ModelReferenceError(
                "subscription_invalid", "subscription_rules entries must be objects"
            )
        rules.append(
            SubscriptionRule(
                harness=str(raw.get("harness") or "").strip(),
                plan=str(raw.get("plan") or "").strip(),
                rule=str(raw.get("rule") or "").strip(),
                pool=_optional_str(raw.get("pool")),
                source_url=_optional_str(raw.get("source_url")),
                checked_at=_optional_str(raw.get("checked_at")),
                is_estimate=bool(raw.get("is_estimate", False)),
            )
        )
        if not rules[-1].harness or not rules[-1].plan or not rules[-1].rule:
            raise ModelReferenceError(
                "subscription_invalid",
                "subscription rule needs harness, plan, and published rule text",
            )
    return ModelRecord(
        model_id=model_id,
        provider=provider,
        display_name=_optional_str(payload.get("display_name")),
        aliases=_tuple_of_str(payload.get("aliases"), "aliases"),
        replacement_model_id=_optional_str(payload.get("replacement_model_id")),
        proposed_tier=tier,  # type: ignore[arg-type]
        tier_evidence=_optional_str(payload.get("tier_evidence")),
        tier_provisional=bool(payload.get("tier_provisional", False)),
        operator_notes=_optional_str(payload.get("operator_notes")),
        api_price=price,
        benchmarks=tuple(benchmarks),
        subscription_rules=tuple(rules),
        source_urls=_tuple_of_str(payload.get("source_urls"), "source_urls"),
        checked_at=_optional_str(payload.get("checked_at")),
    )


__all__ = [
    "ApiPrice",
    "BenchmarkScore",
    "ModelLookup",
    "ModelRecord",
    "ModelReferenceError",
    "PROPOSED_TIERS",
    "ProposedTier",
    "SubscriptionRule",
    "iter_model_records",
    "lookup_api_price",
    "lookup_model_reference",
    "lookup_stem",
    "validate_model_record",
]
