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
