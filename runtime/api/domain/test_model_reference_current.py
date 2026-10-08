"""Published current-model facts."""

from __future__ import annotations

from functools import partial

from yoke_contracts.model_reference import (
    lookup_api_price as _lookup_api_price,
    lookup_model_reference as _lookup_model_reference,
    validate_model_record,
)
from yoke_contracts.model_reference_cursor import CURSOR_RECORDS
from yoke_contracts.model_reference_data import MODEL_RECORDS
from yoke_contracts.model_reference_sources import CURSOR_MODELS_RULE
from yoke_contracts.session_control.plan_limits import (
    CURSOR_MODELS_FAMILIES,
    CURSOR_MODELS_SCOPE,
    cursor_scope_for_model,
)

lookup_api_price = partial(_lookup_api_price, records=MODEL_RECORDS)
lookup_model_reference = partial(_lookup_model_reference, records=MODEL_RECORDS)


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


def test_cursor_models_pool_rule_and_classifier_share_one_family_list() -> None:
    assert all(family in CURSOR_MODELS_RULE.rule for family in CURSOR_MODELS_FAMILIES)
    for record in CURSOR_RECORDS:
        assert CURSOR_MODELS_RULE in record.subscription_rules
        for selector in (record.model_id, *record.aliases):
            assert cursor_scope_for_model(selector) == CURSOR_MODELS_SCOPE


def test_gpt6_workhorse_and_small_model_keep_credits_distinct_from_api_usd() -> None:
    for model_id, dollars, credits in (
        ("gpt-6-sol", (2, 10), (50, 5, 250)),
        ("gpt-6-luna", (0.1, 0.5), (2.5, 0.25, 12.5)),
    ):
        lookup = lookup_model_reference(model_id)
        assert lookup.record is not None
        assert validate_model_record(lookup.record.to_dict()) == lookup.record
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
