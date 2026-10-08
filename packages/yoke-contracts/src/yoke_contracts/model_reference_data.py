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

from yoke_contracts.model_reference_cursor import CURSOR_RECORDS
from yoke_contracts.model_reference_openai import OPENAI_RECORDS
from yoke_contracts.model_reference_records import ModelRecord
from yoke_contracts.model_reference_sources import (
    ANTHROPIC_PRICING,
    CHECKED_AT,
    CLAUDE_MAX_RULE,
    CURSOR_OTHER_RULE,
    CURSOR_PRICING,
    OPUS_55_DOCS,
    REFRESHED_AT,
    claude_price,
)

ANTHROPIC_RECORDS: tuple[ModelRecord, ...] = (
    ModelRecord(
        model_id="claude-opus-5-5",
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
        subscription_rules=(CLAUDE_MAX_RULE, CURSOR_OTHER_RULE),
        source_urls=(OPUS_55_DOCS, ANTHROPIC_PRICING, CURSOR_PRICING),
        checked_at=REFRESHED_AT,
    ),
    ModelRecord(
        model_id="claude-opus-5",
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
        subscription_rules=(CLAUDE_MAX_RULE, CURSOR_OTHER_RULE),
        source_urls=(ANTHROPIC_PRICING, CURSOR_PRICING),
        checked_at=REFRESHED_AT,
    ),
    ModelRecord(
        model_id="claude-sonnet-5",
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
        subscription_rules=(CLAUDE_MAX_RULE, CURSOR_OTHER_RULE),
        source_urls=(ANTHROPIC_PRICING, CURSOR_PRICING),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="claude-opus-4-8",
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
        subscription_rules=(CLAUDE_MAX_RULE, CURSOR_OTHER_RULE),
        source_urls=(ANTHROPIC_PRICING, CURSOR_PRICING),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="claude-fable-5-1",
        provider="anthropic",
        display_name="Claude Fable 5.1",
        aliases=("claude-fable-5.1",),
        api_price=claude_price(
            input_usd=10.0,
            output_usd=50.0,
            cache_read=0.25,
            cache_write=12.50,
            cache_write_long=20.0,
            conditions="Standard API. Cache hits are 0.025x input, not 0.1x.",
        ),
        subscription_rules=(CLAUDE_MAX_RULE,),
        source_urls=(ANTHROPIC_PRICING,),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="claude-fable-5",
        provider="anthropic",
        display_name="Claude Fable 5",
        replacement_model_id="claude-fable-5-1",
        api_price=claude_price(
            input_usd=10.0,
            output_usd=50.0,
            cache_read=1.0,
            cache_write=12.50,
            cache_write_long=20.0,
            conditions="Standard API. Cache hits are the standard 0.1x input.",
        ),
        subscription_rules=(CLAUDE_MAX_RULE,),
        source_urls=(ANTHROPIC_PRICING,),
        checked_at=CHECKED_AT,
    ),
)

MODEL_RECORDS: tuple[ModelRecord, ...] = (
    CURSOR_RECORDS + ANTHROPIC_RECORDS + OPENAI_RECORDS
)
