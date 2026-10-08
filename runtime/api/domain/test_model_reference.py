"""Sourced model-reference reader, validator, and registered handlers."""

from __future__ import annotations

import re
from functools import partial
from pathlib import Path

import pytest

from yoke_contracts.model_reference import (
    ModelReferenceError,
    lookup_api_price as _lookup_api_price,
    lookup_model_reference as _lookup_model_reference,
    validate_model_record,
)
from yoke_contracts.model_reference_data import MODEL_RECORDS

lookup_api_price = partial(_lookup_api_price, records=MODEL_RECORDS)
lookup_model_reference = partial(_lookup_model_reference, records=MODEL_RECORDS)


def test_unknown_model_is_explicitly_unresearched() -> None:
    lookup = lookup_model_reference("not-a-real-model")
    assert lookup.researched is False
    assert lookup.record is None
    assert lookup_api_price("not-a-real-model") is None


def test_cursor_effort_suffix_hits_the_canonical_grok_record() -> None:
    lookup = lookup_model_reference("cursor-grok-4.7-high")
    assert lookup.researched is True
    assert lookup.record is not None
    assert lookup.record.model_id == "cursor-grok-4.7"
    assert "operator_preferences" not in lookup.record.to_dict()


_TEACHING_FILES = (
    ".agents/skills/yoke/models/SKILL.md",
    ".agents/skills/yoke/steer/model-selection.md",
    "docs/public/cli-and-config.md",
)
_FENCED_BLOCK_RE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
_TIER_CLAIM_RE = re.compile(r"tier\s?-?[12]\b|\bexcluded\b", re.IGNORECASE)


def _prose_sentences(path: Path) -> list[str]:
    """Return the file's sentences with fenced blocks removed.

    A fenced block is a syntax example — the ``[1m]`` context suffix, the
    ``-high`` effort suffix — and each one says in prose that its model
    ids are illustrative. Only the prose makes claims.
    """
    prose = " ".join(_FENCED_BLOCK_RE.sub(" ", path.read_text()).split())
    return re.split(r"(?<=[.!?])\s+", prose)


def test_teaching_prose_never_claims_a_models_tier() -> None:
    """Which model sits in a tier is live configuration, never taught prose.

    Routing changes without a code lane, so prose naming which models sit
    in a tier goes stale with nothing to correct it. Naming a model as a
    selector-syntax example stays fine; claiming its tier in the same
    sentence does not.
    """
    root = Path(__file__).resolve().parents[3]
    names = sorted(
        {record.display_name for record in MODEL_RECORDS}
        | {record.model_id for record in MODEL_RECORDS},
        key=len,
        reverse=True,
    )
    claims: list[str] = []
    for rel in _TEACHING_FILES:
        for sentence in _prose_sentences(root / rel):
            named = [name for name in names if name in sentence]
            if named and _TIER_CLAIM_RE.search(sentence):
                claims.append(f"{rel}: {named} in {sentence!r}")
    assert not claims, (
        "taught prose claims a tier for a specific model; state the tier's "
        "meaning and send the reader to the live routing read instead:\n"
        + "\n".join(claims)
    )


def test_reference_teaching_retains_its_settled_corrections() -> None:
    root = Path(__file__).resolve().parents[3]
    joined = "\n".join((root / rel).read_text() for rel in _TEACHING_FILES)
    for rel in _TEACHING_FILES[1:]:
        assert "proposed_tier" not in (root / rel).read_text(), rel
    assert "Grok 4.6 is tier 1" not in joined
    assert "bounded-work default" not in joined
    assert "do not exclude" not in joined.lower()
    assert "claude-sonnet-5" not in joined.split("session_model_routing", 1)[-1]


def test_claude_cache_write_fields_split_five_minute_and_one_hour() -> None:
    price = lookup_api_price("claude-opus-5")
    assert price is not None
    assert price.cache_write_per_million_usd == 6.25
    assert price.cache_write_long_per_million_usd == 10.0
    grok_price = lookup_api_price("cursor-grok-4.6")
    assert grok_price is not None
    assert grok_price.cache_write_long_per_million_usd is None


def test_validate_refuses_unknown_efforts_windows_and_missing_identity() -> None:
    for extra, code in (
        ({"reasoning_efforts": ["turbo"]}, "reasoning_efforts_invalid"),
        ({"context_window_tokens": [0]}, "context_windows_invalid"),
        ({"context_window_tokens": "1M"}, "context_windows_invalid"),
    ):
        with pytest.raises(ModelReferenceError) as raised:
            validate_model_record({"model_id": "x", "provider": "y", **extra})
        assert raised.value.code == code
    with pytest.raises(ModelReferenceError) as raised:
        validate_model_record({"model_id": "", "provider": ""})
    assert raised.value.code == "record_invalid"


def test_validate_reads_published_efforts_and_windows() -> None:
    record = validate_model_record(
        {
            "model_id": "example-model",
            "provider": "example",
            "reasoning_efforts": ["LOW", "high"],
            "context_window_tokens": [1_000_000, 200_000, 200_000],
        }
    )
    assert record.reasoning_efforts == ("low", "high")
    assert record.context_window_tokens == (200_000, 1_000_000)
    assert validate_model_record(record.to_dict()) == record


def test_validate_accepts_null_unknown_leaves() -> None:
    record = validate_model_record(
        {
            "model_id": "example-model",
            "provider": "example",
            "reasoning_efforts": None,
            "context_window_tokens": None,
            "api_price": None,
            "benchmarks": [],
        }
    )
    assert record.model_id == "example-model"
    assert record.reasoning_efforts == ()
    assert record.context_window_tokens == ()
    assert record.api_price is None
    assert record.benchmarks == ()


def test_seeded_document_survives_its_own_validator() -> None:
    records = MODEL_RECORDS
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
