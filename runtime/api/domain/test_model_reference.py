"""Sourced model-reference reader, validator, and registered handlers."""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.model_reference import (
    ModelReferenceError,
    iter_model_records,
    lookup_api_price,
    lookup_model_reference,
    validate_model_record,
)
from yoke_core.domain.handlers import __init_register__ as init_register
from yoke_core.domain.handlers import _register_models, model_reference
from yoke_core.domain import yoke_function_registry


def _request(function_id: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(session_id="s-test"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_unknown_model_is_explicitly_unresearched() -> None:
    lookup = lookup_model_reference("not-a-real-model")
    assert lookup.researched is False
    assert lookup.record is None
    assert lookup_api_price("not-a-real-model") is None


def test_cursor_effort_suffix_hits_the_canonical_grok_record() -> None:
    lookup = lookup_model_reference("cursor-grok-4.6-high")
    assert lookup.researched is True
    assert lookup.record is not None
    assert lookup.record.model_id == "cursor-grok-4.6"
    assert lookup.record.proposed_tier == "tier1"
    assert "Grok 4.6" in (lookup.record.operator_notes or "")
    assert "operator_preferences" not in lookup.record.to_dict()


def test_sonnet_is_tier2_not_excluded() -> None:
    lookup = lookup_model_reference("claude-sonnet-5")
    assert lookup.researched is True
    assert lookup.record is not None
    assert lookup.record.proposed_tier == "tier2"
    assert lookup.record.proposed_tier != "excluded"


def test_claude_cache_write_fields_split_five_minute_and_one_hour() -> None:
    price = lookup_api_price("claude-opus-5")
    assert price is not None
    assert price.cache_write_per_million_usd == 6.25
    assert price.cache_write_long_per_million_usd == 10.0
    grok_price = lookup_api_price("cursor-grok-4.6")
    assert grok_price is not None
    assert grok_price.cache_write_long_per_million_usd is None


def test_validate_refuses_unknown_tier_and_missing_identity() -> None:
    with pytest.raises(ModelReferenceError) as raised:
        validate_model_record(
            {"model_id": "x", "provider": "y", "proposed_tier": "gold"}
        )
    assert raised.value.code == "tier_invalid"
    with pytest.raises(ModelReferenceError) as raised:
        validate_model_record({"model_id": "", "provider": ""})
    assert raised.value.code == "record_invalid"


def test_validate_accepts_null_unknown_leaves() -> None:
    record = validate_model_record(
        {
            "model_id": "example-model",
            "provider": "example",
            "proposed_tier": None,
            "api_price": None,
            "benchmarks": [],
        }
    )
    assert record.model_id == "example-model"
    assert record.proposed_tier is None
    assert record.api_price is None
    assert record.benchmarks == ()


def test_lookup_handler_returns_unresearched_without_raising() -> None:
    outcome = model_reference.handle_models_lookup(
        _request(model_reference.LOOKUP_FUNCTION_ID, {"model_id": "missing"})
    )
    assert outcome.primary_success is True
    assert outcome.result_payload["researched"] is False
    assert outcome.result_payload["record"] is None


def test_validate_handler_names_the_refusal_code() -> None:
    outcome = model_reference.handle_models_validate(
        _request(
            model_reference.VALIDATE_FUNCTION_ID,
            {"record": {"model_id": "x", "provider": "y", "proposed_tier": "gold"}},
        )
    )
    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "tier_invalid"


def test_get_handler_lists_seeded_records() -> None:
    outcome = model_reference.handle_models_get(
        _request(model_reference.GET_FUNCTION_ID, {})
    )
    assert outcome.primary_success is True
    assert outcome.result_payload["count"] >= 1
    ids = {row["model_id"] for row in outcome.result_payload["records"]}
    assert "cursor-grok-4.6" in ids
    assert "claude-sonnet-5" in ids


def test_models_handlers_are_registered_as_session_optional_reads() -> None:
    init_register.register_all_handlers()
    assert _register_models in init_register._DOMAIN_REGISTRARS
    for function_id in (
        model_reference.LOOKUP_FUNCTION_ID,
        model_reference.GET_FUNCTION_ID,
        model_reference.VALIDATE_FUNCTION_ID,
    ):
        entry = yoke_function_registry.lookup(function_id)
        assert entry is not None
        assert entry.target_kinds == ("global",)
        assert entry.claim_required_kind is None
        assert entry.ambient_session_required is False
        assert entry.adapter_status == "live"
        assert entry.side_effects == ()


def test_seeded_document_survives_its_own_validator() -> None:
    records = iter_model_records()
    assert records
    for record in records:
        assert validate_model_record(record.to_dict()) == record


def test_astra_carries_published_rates_and_a_credit_weight_not_dollars() -> None:
    lookup = lookup_model_reference("gpt-6-astra")
    assert lookup.researched is True
    assert lookup.record is not None
    price = lookup.record.api_price
    assert price is not None
    assert (price.input_per_million_usd, price.output_per_million_usd) == (10.0, 50.0)
    assert price.cache_read_per_million_usd == 1.0
    assert price.cache_write_per_million_usd == 12.50
    assert price.estimated_fields == ()
    assert "standard rate" in (price.conditions or "").lower()
    weight = lookup.record.subscription_rules[0].consumption_weight
    assert weight is not None
    assert weight.unit == "credits"
    assert weight.input_per_million == 250.0
    assert weight.output_per_million == 1250.0
    assert not hasattr(weight, "usd")


def test_fable_versions_keep_their_own_cache_hit_rates() -> None:
    assert lookup_model_reference("claude-fable-5.1").record.model_id == (
        "claude-fable-5-1"
    )
    assert lookup_api_price("claude-fable-5-1").cache_read_per_million_usd == 0.25
    assert lookup_api_price("claude-fable-5").cache_read_per_million_usd == 1.0


def test_an_inferred_rate_is_filled_only_with_its_label_and_basis() -> None:
    price = lookup_api_price("gpt-5.5")
    assert price is not None
    assert price.estimated_fields == ("cache_write_per_million_usd",)
    assert price.cache_write_per_million_usd == 6.25
    assert "1.25x" in (price.estimate_basis or "")
    published = lookup_api_price("gpt-5.6-sol")
    assert published is not None
    assert published.cache_write_per_million_usd == 5.0
    assert published.estimated_fields == ()


def test_validate_refuses_an_estimate_label_it_cannot_stand_behind() -> None:
    base = {"model_id": "x", "provider": "y"}
    unlabelled_field = {
        **base,
        "api_price": {
            "input_per_million_usd": 1.0,
            "estimated_fields": ["output_per_million_usd"],
            "estimate_basis": "reasoned from the family",
        },
    }
    with pytest.raises(ModelReferenceError) as raised:
        validate_model_record(unlabelled_field)
    assert raised.value.code == "estimate_invalid"

    no_basis = {
        **base,
        "api_price": {
            "input_per_million_usd": 1.0,
            "estimated_fields": ["input_per_million_usd"],
        },
    }
    with pytest.raises(ModelReferenceError) as raised:
        validate_model_record(no_basis)
    assert raised.value.code == "estimate_invalid"

    basis_without_label = {
        **base,
        "api_price": {"input_per_million_usd": 1.0, "estimate_basis": "a hunch"},
    }
    with pytest.raises(ModelReferenceError) as raised:
        validate_model_record(basis_without_label)
    assert raised.value.code == "estimate_invalid"

    unknown_field = {
        **base,
        "api_price": {
            "input_per_million_usd": 1.0,
            "estimated_fields": ["subscription_per_million_usd"],
            "estimate_basis": "a hunch",
        },
    }
    with pytest.raises(ModelReferenceError) as raised:
        validate_model_record(unknown_field)
    assert raised.value.code == "estimate_invalid"


def test_validate_accepts_a_labelled_estimated_weighting() -> None:
    record = validate_model_record(
        {
            "model_id": "x",
            "provider": "y",
            "subscription_rules": [
                {
                    "harness": "codex",
                    "plan": "pro",
                    "rule": "published per-model credit rate",
                    "is_estimate": True,
                    "estimate_basis": "no published weight; inferred from siblings",
                    "consumption_weight": {
                        "unit": "credits",
                        "input_per_million": 100.0,
                        "is_estimate": True,
                        "estimate_basis": "sibling model rate",
                    },
                }
            ],
        }
    )
    weight = record.subscription_rules[0].consumption_weight
    assert weight is not None
    assert weight.is_estimate is True
    assert weight.input_per_million == 100.0


def test_validate_refuses_an_unusable_consumption_weight() -> None:
    base = {"harness": "codex", "plan": "pro", "rule": "text"}
    with pytest.raises(ModelReferenceError) as raised:
        validate_model_record(
            {
                "model_id": "x",
                "provider": "y",
                "subscription_rules": [
                    {**base, "consumption_weight": {"input_per_million": 5.0}}
                ],
            }
        )
    assert raised.value.code == "consumption_invalid"
    with pytest.raises(ModelReferenceError) as raised:
        validate_model_record(
            {
                "model_id": "x",
                "provider": "y",
                "subscription_rules": [
                    {**base, "consumption_weight": {"unit": "credits"}}
                ],
            }
        )
    assert raised.value.code == "consumption_invalid"


def test_validate_refuses_an_unexplained_estimated_subscription_rule() -> None:
    with pytest.raises(ModelReferenceError) as raised:
        validate_model_record(
            {
                "model_id": "x",
                "provider": "y",
                "subscription_rules": [
                    {
                        "harness": "codex",
                        "plan": "pro",
                        "rule": "text",
                        "is_estimate": True,
                    }
                ],
            }
        )
    assert raised.value.code == "estimate_invalid"
