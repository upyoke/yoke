"""Seeded current model-reference document. Refresh by editing family modules.

Records describe models only; the execution levels decide which model a
worker launches. Published reasoning efforts and context windows stay empty
until a provider page states them. Prices and subscription rules are copied from public primary sources
on CHECKED_AT. Unknown leaves stay None; an inferred rate is filled only with
its ``estimated_fields`` label and a stated basis. API dollars are not
subscription percentages: a plan's own metered weighting rides on the
subscription rule as a consumption weight and is never summed with money.
Benchmarks stay empty until a named public result is attached.
"""

from __future__ import annotations

from yoke_contracts.model_reference import validate_model_record

from yoke_contracts.model_reference_cursor import CURSOR_RECORDS
from yoke_contracts.model_reference_openai import OPENAI_RECORDS
from yoke_contracts.model_reference_records import ModelRecord
from yoke_contracts.model_reference_sources import (
    ANTHROPIC_PRICING,
    CLAUDE_ULTRA_RULE,
    CURSOR_OTHER_RULE,
    CURSOR_PRICING,
    OPUS_55_DOCS,
    REFRESHED_AT,
    claude_price,
)

ANTHROPIC_RECORDS: tuple[ModelRecord, ...] = (
    validate_model_record(
        {
            "aliases": [],
            "api_price": {
                "cache_read_per_million_usd": 0.2,
                "cache_write_long_per_million_usd": 16.0,
                "cache_write_per_million_usd": 10.0,
                "checked_at": "2026-11-09",
                "conditions": "Standard API. Fast mode is $16/$80. Cache hits are 0.025x input. Requires 30-day data retention (no ZDR unless authorized).",
                "effective_at": "2026-11-09",
                "estimate_basis": None,
                "estimated_fields": [],
                "input_per_million_usd": 8.0,
                "output_per_million_usd": 40.0,
                "source_url": "https://platform.claude.com/docs/en/about-claude/pricing"
            },
            "benchmarks": [],
            "checked_at": "2026-11-09",
            "context_window_tokens": [
                1000000
            ],
            "display_name": "Claude Fable 5.2",
            "model_id": "claude-fable-5-2",
            "operator_notes": None,
            "provider": "anthropic",
            "reasoning_efforts": [
                "low",
                "medium",
                "high",
                "xhigh",
                "max"
            ],
            "replacement_model_id": None,
            "source_urls": [
                "https://platform.claude.com/docs/en/models/fable-5-2/overview",
                "https://platform.claude.com/docs/en/about-claude/pricing",
                "https://platform.claude.com/docs/en/build-with-claude/effort",
                "https://www.anthropic.com/claude-fable-and-mythos-5-2"
            ],
            "subscription_rules": [
                {
                    "checked_at": "2026-11-09",
                    "consumption_weight": None,
                    "estimate_basis": None,
                    "harness": "claude",
                    "is_estimate": False,
                    "plan": "ultra",
                    "pool": "included",
                    "rule": "Ultra (the renamed Max 20x plan, $200/month) gives 10 times the Pro plan's usage every week. Verified Ultra accounts have no five-hour limit; unverified accounts get a temporary limit. A weekly limit applies across all models. No token-to-percent conversion is published, and the page reserves further discretionary limiting (weekly/monthly caps, model and feature usage). Ultra also has a separate weekly limit for Fable; claude.com/pricing lists Fable at 50% of weekly limits.",
                    "source_url": "https://support.claude.com/en/articles/17728952-what-is-the-ultra-plan"
                }
            ]
        }
    ),
    validate_model_record(
        {
            "aliases": [],
            "api_price": {
                "cache_read_per_million_usd": 0.01,
                "cache_write_long_per_million_usd": 0.2,
                "cache_write_per_million_usd": 0.125,
                "checked_at": "2026-10-08",
                "conditions": "Prompts up to 100,000 tokens. Above 100,000: input $0.50, output $2.50, cache read $0.05, 5m write $0.625, 1h write $1 per MTok.",
                "effective_at": None,
                "estimate_basis": None,
                "estimated_fields": [],
                "input_per_million_usd": 0.1,
                "output_per_million_usd": 0.5,
                "source_url": "https://platform.claude.com/docs/en/models/haiku-5-5/overview",
            },
            "benchmarks": [],
            "checked_at": "2026-10-12",
            "context_window_tokens": [1000000],
            "display_name": "Claude Haiku 5.5",
            "model_id": "claude-haiku-5-5",
            "operator_notes": None,
            "provider": "anthropic",
            "reasoning_efforts": ["low", "medium", "high", "xhigh", "max"],
            "replacement_model_id": None,
            "source_urls": [
                "https://platform.claude.com/docs/en/models/haiku-5-5/overview",
                "https://platform.claude.com/docs/en/build-with-claude/effort",
            ],
            "subscription_rules": [],
        }
    ),
    validate_model_record(
        {
            "aliases": [],
            "api_price": {
                "cache_read_per_million_usd": 0.1,
                "cache_write_long_per_million_usd": 4,
                "cache_write_per_million_usd": 2.5,
                "checked_at": "2026-10-08",
                "conditions": "Standard API pricing; batch input/output 50% discount.",
                "effective_at": None,
                "estimate_basis": None,
                "estimated_fields": [],
                "input_per_million_usd": 2,
                "output_per_million_usd": 10,
                "source_url": "https://platform.claude.com/docs/en/models/sonnet-5-5/overview",
            },
            "benchmarks": [],
            "checked_at": "2026-10-12",
            "context_window_tokens": [1000000],
            "display_name": "Claude Sonnet 5.5",
            "model_id": "claude-sonnet-5-5",
            "operator_notes": None,
            "provider": "anthropic",
            "reasoning_efforts": ["low", "medium", "high", "xhigh", "max"],
            "replacement_model_id": None,
            "source_urls": [
                "https://platform.claude.com/docs/en/models/sonnet-5-5/overview",
                "https://platform.claude.com/docs/en/build-with-claude/effort",
            ],
            "subscription_rules": [],
        }
    ),
    ModelRecord(
        model_id="claude-opus-5-5",
        reasoning_efforts=(
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ),
        provider="anthropic",
        display_name="Claude Opus 5.5",
        api_price=claude_price(
            input_usd=4.0,
            output_usd=20.0,
            cache_read=0.20,
            cache_write=5.0,
            cache_write_long=8.0,
            conditions="Standard API. Fast mode is $8/$40; cache hits are 0.05x input.",
            checked_at=REFRESHED_AT,
        ),
        subscription_rules=(CLAUDE_ULTRA_RULE, CURSOR_OTHER_RULE),
        source_urls=(OPUS_55_DOCS, ANTHROPIC_PRICING, CURSOR_PRICING),
        checked_at="2026-10-12",
    ),
    ModelRecord(
        model_id="claude-opus-5",
        reasoning_efforts=(
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ),
        replacement_model_id="claude-opus-5-5",
        provider="anthropic",
        display_name="Claude Opus 5",
        api_price=claude_price(
            input_usd=5.0,
            output_usd=25.0,
            cache_read=0.50,
            cache_write=6.25,
            cache_write_long=10.0,
            conditions="Standard API. Fast mode is $10/$50. Writes: 5m=1.25x, 1h=2x.",
        ),
        subscription_rules=(CLAUDE_ULTRA_RULE, CURSOR_OTHER_RULE),
        source_urls=(ANTHROPIC_PRICING, CURSOR_PRICING),
        checked_at="2026-10-12",
    ),
    ModelRecord(
        model_id="claude-sonnet-5",
        reasoning_efforts=(
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ),
        replacement_model_id="claude-sonnet-5-5",
        provider="anthropic",
        display_name="Claude Sonnet 5",
        api_price=claude_price(
            input_usd=2.0,
            output_usd=10.0,
            cache_read=0.20,
            cache_write=2.50,
            cache_write_long=4.0,
            conditions="Standard API. $2/$10 is the standing Sonnet 5 price.",
        ),
        subscription_rules=(CLAUDE_ULTRA_RULE, CURSOR_OTHER_RULE),
        source_urls=(ANTHROPIC_PRICING, CURSOR_PRICING),
        checked_at="2026-10-12",
    ),
    ModelRecord(
        model_id="claude-opus-4-8",
        reasoning_efforts=(
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ),
        replacement_model_id="claude-opus-5-5",
        provider="anthropic",
        display_name="Claude Opus 4.8",
        api_price=claude_price(
            input_usd=5.0,
            output_usd=25.0,
            cache_read=0.50,
            cache_write=6.25,
            cache_write_long=10.0,
            conditions="Standard API. Fast mode is $10/$50.",
        ),
        subscription_rules=(CLAUDE_ULTRA_RULE, CURSOR_OTHER_RULE),
        source_urls=(ANTHROPIC_PRICING, CURSOR_PRICING),
        checked_at="2026-10-12",
    ),
    ModelRecord(
        model_id="claude-fable-5-1",
        reasoning_efforts=(
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ),
        provider="anthropic",
        display_name="Claude Fable 5.1",
        replacement_model_id="claude-fable-5-2",
        aliases=("claude-fable-5.1",),
        api_price=claude_price(
            input_usd=10.0,
            output_usd=50.0,
            cache_read=0.25,
            cache_write=12.50,
            cache_write_long=20.0,
            conditions="Standard API. Cache hits are 0.025x input, not 0.1x.",
        ),
        subscription_rules=(CLAUDE_ULTRA_RULE,),
        source_urls=(ANTHROPIC_PRICING,),
        checked_at="2026-10-12",
    ),
    ModelRecord(
        model_id="claude-fable-5",
        reasoning_efforts=(
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ),
        provider="anthropic",
        display_name="Claude Fable 5",
        replacement_model_id="claude-fable-5-2",
        api_price=claude_price(
            input_usd=10.0,
            output_usd=50.0,
            cache_read=1.0,
            cache_write=12.50,
            cache_write_long=20.0,
            conditions="Standard API. Cache hits are the standard 0.1x input.",
        ),
        subscription_rules=(CLAUDE_ULTRA_RULE,),
        source_urls=(ANTHROPIC_PRICING,),
        checked_at="2026-10-12",
    ),
)

MODEL_RECORDS: tuple[ModelRecord, ...] = (
    CURSOR_RECORDS + ANTHROPIC_RECORDS + OPENAI_RECORDS
)
