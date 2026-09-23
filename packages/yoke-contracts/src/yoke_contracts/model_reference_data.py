"""Seeded current model-reference document. Refresh by editing family modules.

``proposed_tier`` is global capability relative to the absolute frontier
across providers, not a vendor product ladder or the best model a harness
offers. Prices and subscription rules are copied from public primary sources
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
        proposed_tier="tier2",
        tier_evidence=(
            "Current Opus sits immediately below the Fable/Astra frontier. "
            "Anthropic positions Fable 5.1 above Opus 5.5 for demanding "
            "reasoning; this global tier is not inferred from price."
        ),
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
        proposed_tier="excluded",
        tier_evidence=(
            "Prior Opus release. Opus 5.5 now occupies the current tier2 "
            "band; the old flagship label does not retain that rank."
        ),
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
        proposed_tier="excluded",
        tier_evidence=(
            "Below the usable floor for ordinary steering selections. Price "
            "and Anthropic's own mid-ladder label are not a worker default."
        ),
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
        proposed_tier="excluded",
        tier_evidence=(
            "Prior-generation Opus. Re-evaluated rather than kept as a "
            "flagship; current Opus 5.5 occupies the tier2 band."
        ),
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
        proposed_tier="tier1",
        tier_evidence=(
            "Absolute-frontier Fable family. Operator-approved global tier1; "
            "not inferred from price, version, or Anthropic's product ladder. "
            "5.1 is a separate pricing row because its cache hits are cheaper."
        ),
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
        proposed_tier="tier1",
        tier_evidence=(
            "Prior Fable release, still the same frontier family; 5.1 is the "
            "successor. Cache hits are $1; the 5.1 row prices that hit at $0.25."
        ),
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
