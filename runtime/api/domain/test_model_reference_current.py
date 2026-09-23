"""Published current-model facts and the separate routing annotation."""

from __future__ import annotations

from yoke_contracts.model_reference import (
    lookup_api_price,
    lookup_model_reference,
    validate_model_record,
)


def test_current_opus_prices_five_minute_and_one_hour_cache_separately() -> None:
    lookup = lookup_model_reference("claude-opus-5-5")
    assert lookup.record is not None
    assert validate_model_record(lookup.record.to_dict()) == lookup.record
    price = lookup_api_price("claude-opus-5-5")
    assert price is not None
    assert (price.input_per_million_usd, price.output_per_million_usd) == (4, 20)
    assert price.cache_read_per_million_usd == 0.2
    assert price.cache_write_per_million_usd == 5
    assert price.cache_write_long_per_million_usd == 8


def test_current_grok_selector_and_pool_price() -> None:
    lookup = lookup_model_reference("cursor-grok-4.7-xhigh")
    assert lookup.record is not None
    assert lookup.record.model_id == "cursor-grok-4.7"
    assert lookup.record.subscription_rules[0].pool == "cursor-models"
    price = lookup.record.api_price
    assert price is not None
    assert (price.input_per_million_usd, price.output_per_million_usd) == (2, 6)
    assert price.cache_write_per_million_usd is None


def test_gpt6_workhorse_and_small_model_keep_credits_distinct_from_api_usd() -> None:
    for model_id, tier, dollars, credits in (
        ("gpt-6-sol", "tier2", (2, 10), (50, 5, 250)),
        ("gpt-6-luna", "excluded", (0.1, 0.5), (2.5, 0.25, 12.5)),
    ):
        lookup = lookup_model_reference(model_id)
        assert lookup.record is not None
        assert validate_model_record(lookup.record.to_dict()) == lookup.record
        assert lookup.record.proposed_tier == tier
        price = lookup.record.api_price
        assert price is not None
        assert (price.input_per_million_usd, price.output_per_million_usd) == dollars
        weight = lookup.record.subscription_rules[0].consumption_weight
        assert weight is not None
        assert weight.unit == "credits"
        assert (
            weight.input_per_million,
            weight.cached_input_per_million,
            weight.output_per_million,
        ) == credits


def test_approved_cursor_route_is_annotation_despite_older_model_tier() -> None:
    lookup = lookup_model_reference("cursor-grok-4.6-high")
    assert lookup.record is not None
    assert lookup.record.proposed_tier == "excluded"
    assert "Grok 4.6 at high" in (lookup.record.operator_notes or "")
