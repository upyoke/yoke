"""Sourced model reference shared by steering, cost readers, and refresh.

The durable store is this package: typed records plus a seeded document.
Lookup never raises. ``researched=False`` is the explicit not-researched
marker — missing facts are not a discovery, launch, or usage gate.
Researched ``proposed_tier`` is not operator routing; per-surface routing
lives with the steering selection policy, not this reference.

Record shapes live in ``model_reference_records``; this module is the
lookup and validation surface every caller reads. Validation is where the
labelled-estimate rule is enforced: a rate or a plan weighting may be an
estimate, but only a labelled one with a stated basis, and only over a
field that actually carries a number.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from yoke_contracts.model_reference_records import (
    CONSUMPTION_FIELDS,
    PRICE_FIELDS,
    PROPOSED_TIERS,
    ApiPrice,
    BenchmarkScore,
    ConsumptionWeight,
    ModelLookup,
    ModelRecord,
    ModelReferenceError,
    ProposedTier,
    SubscriptionRule,
)
from yoke_contracts.session_model_facts import (
    CLAUDE_CONTEXT_TIER_SUFFIX,
    REASONING_EFFORT_VALUES,
)


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
        raise ModelReferenceError(
            "record_invalid", f"{field} must be a list of strings"
        )
    return tuple(str(item).strip() for item in value if str(item).strip())


def _estimate_labels(
    raw: Mapping[str, Any], values: Mapping[str, Optional[float]], where: str
) -> tuple[tuple[str, ...], Optional[str]]:
    """Validate one labelled-estimate pair against the numbers it covers.

    A label that names a field carrying no number describes nothing, and a
    label with no basis asks the reader to trust an unexplained inference.
    Both refuse here so the stored document can be read at face value.
    """
    labelled = _tuple_of_str(raw.get("estimated_fields"), f"{where} estimated_fields")
    basis = _optional_str(raw.get("estimate_basis"))
    for name in labelled:
        if name not in values:
            raise ModelReferenceError(
                "estimate_invalid",
                f"{where} estimated_fields names {name}; expected one of "
                f"{', '.join(values)}",
            )
        if values[name] is None:
            raise ModelReferenceError(
                "estimate_invalid",
                f"{where} labels {name} an estimate but leaves it null; "
                "give the estimated number or drop the label",
            )
    if labelled and not basis:
        raise ModelReferenceError(
            "estimate_invalid",
            f"{where} estimated_fields needs estimate_basis stating why the "
            "estimate is reasonable",
        )
    if basis and not labelled:
        raise ModelReferenceError(
            "estimate_invalid",
            f"{where} has estimate_basis but names no estimated_fields",
        )
    return labelled, basis


def _api_price(raw: Mapping[str, Any]) -> ApiPrice:
    rates = {name: _optional_float(raw.get(name), name) for name in PRICE_FIELDS}
    labelled, basis = _estimate_labels(raw, rates, "api_price")
    return ApiPrice(
        conditions=_optional_str(raw.get("conditions")),
        source_url=_optional_str(raw.get("source_url")),
        checked_at=_optional_str(raw.get("checked_at")),
        effective_at=_optional_str(raw.get("effective_at")),
        estimated_fields=labelled,
        estimate_basis=basis,
        **rates,
    )


def _consumption_weight(raw: object) -> Optional[ConsumptionWeight]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ModelReferenceError(
            "consumption_invalid", "consumption_weight must be an object or null"
        )
    unit = str(raw.get("unit") or "").strip()
    if not unit:
        raise ModelReferenceError(
            "consumption_invalid",
            "consumption_weight needs the unit the plan publishes, such as credits",
        )
    rates = {name: _optional_float(raw.get(name), name) for name in CONSUMPTION_FIELDS}
    if all(value is None for value in rates.values()):
        raise ModelReferenceError(
            "consumption_invalid",
            "consumption_weight carries no rate; state the plan's weighting in "
            "the rule text instead",
        )
    is_estimate = bool(raw.get("is_estimate", False))
    basis = _optional_str(raw.get("estimate_basis"))
    if is_estimate and not basis:
        raise ModelReferenceError(
            "estimate_invalid",
            "an estimated consumption_weight needs estimate_basis",
        )
    if basis and not is_estimate:
        raise ModelReferenceError(
            "estimate_invalid",
            "consumption_weight has estimate_basis but is not marked is_estimate",
        )
    return ConsumptionWeight(
        unit=unit,
        is_estimate=is_estimate,
        estimate_basis=basis,
        source_url=_optional_str(raw.get("source_url")),
        checked_at=_optional_str(raw.get("checked_at")),
        **rates,
    )


def _subscription_rule(raw: object) -> SubscriptionRule:
    if not isinstance(raw, Mapping):
        raise ModelReferenceError(
            "subscription_invalid", "subscription_rules entries must be objects"
        )
    rule = SubscriptionRule(
        harness=str(raw.get("harness") or "").strip(),
        plan=str(raw.get("plan") or "").strip(),
        rule=str(raw.get("rule") or "").strip(),
        pool=_optional_str(raw.get("pool")),
        source_url=_optional_str(raw.get("source_url")),
        checked_at=_optional_str(raw.get("checked_at")),
        is_estimate=bool(raw.get("is_estimate", False)),
        estimate_basis=_optional_str(raw.get("estimate_basis")),
        consumption_weight=_consumption_weight(raw.get("consumption_weight")),
    )
    if not rule.harness or not rule.plan or not rule.rule:
        raise ModelReferenceError(
            "subscription_invalid",
            "subscription rule needs harness, plan, and published rule text",
        )
    if rule.is_estimate and not rule.estimate_basis:
        raise ModelReferenceError(
            "estimate_invalid",
            "an estimated subscription rule needs estimate_basis stating why "
            "the estimate is reasonable",
        )
    if rule.estimate_basis and not rule.is_estimate:
        raise ModelReferenceError(
            "estimate_invalid",
            "subscription rule has estimate_basis but is not marked is_estimate",
        )
    return rule


def _benchmark(raw: object) -> BenchmarkScore:
    if not isinstance(raw, Mapping) or not str(raw.get("name") or "").strip():
        raise ModelReferenceError("benchmark_invalid", "each benchmark needs a name")
    score = raw.get("score")
    return BenchmarkScore(
        name=str(raw.get("name")).strip(),
        version=_optional_str(raw.get("version")),
        score=None if score is None else _optional_float(score, "score"),
        tested_model=_optional_str(raw.get("tested_model")),
        tested_harness=_optional_str(raw.get("tested_harness")),
        tested_reasoning=_optional_str(raw.get("tested_reasoning")),
        source_url=_optional_str(raw.get("source_url")),
        checked_at=_optional_str(raw.get("checked_at")),
    )


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
    if price_raw is not None and not isinstance(price_raw, Mapping):
        raise ModelReferenceError(
            "price_invalid", "api_price must be an object or null"
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
        api_price=None if price_raw is None else _api_price(price_raw),
        benchmarks=tuple(_benchmark(raw) for raw in payload.get("benchmarks") or ()),
        subscription_rules=tuple(
            _subscription_rule(raw) for raw in payload.get("subscription_rules") or ()
        ),
        source_urls=_tuple_of_str(payload.get("source_urls"), "source_urls"),
        checked_at=_optional_str(payload.get("checked_at")),
    )


__all__ = [
    "ApiPrice",
    "BenchmarkScore",
    "ConsumptionWeight",
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
