"""Seeded current model-reference document. Refresh by editing family modules.

Prices and subscription rules are copied from public primary sources on
CHECKED_AT. Unknown leaves stay None. API dollars are not subscription
percentages. Benchmarks stay empty until a named public result is attached.
"""

from __future__ import annotations

from yoke_contracts.model_reference import ApiPrice, ModelRecord
from yoke_contracts.model_reference_cursor import CURSOR_RECORDS
from yoke_contracts.model_reference_sources import (
    ANTHROPIC_PRICING,
    CHECKED_AT,
    CLAUDE_MAX_RULE,
    CODEX_PRO_PLAN,
    CODEX_PRO_RULE,
    CURSOR_OTHER_RULE,
    CURSOR_PRICING,
    claude_price,
)

_PROVIDER_RECORDS: tuple[ModelRecord, ...] = (
    ModelRecord(
        model_id="claude-opus-5",
        provider="anthropic",
        display_name="Claude Opus 5",
        aliases=("claude-opus-5-fast",),
        proposed_tier="tier1",
        tier_evidence=(
            "Anthropic current flagship for complex agentic coding. Fast mode "
            "is a speed/price variant of the same model, not a different tier."
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
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="claude-sonnet-5",
        provider="anthropic",
        display_name="Claude Sonnet 5",
        proposed_tier="tier2",
        tier_evidence=(
            "Anthropic current high-performance coding model at $2/$10. Do not "
            "exclude it from a blanket 'use stronger models at lower reasoning' "
            "claim; it remains the bounded-work default."
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
        proposed_tier="tier1",
        tier_evidence=(
            "Still listed on Anthropic's current pricing table at Opus rates. "
            "No published replacement alias from Anthropic."
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
        model_id="claude-fable-5",
        provider="anthropic",
        display_name="Claude Fable 5",
        aliases=("claude-fable-5.1",),
        proposed_tier="tier1",
        tier_provisional=True,
        tier_evidence=(
            "Anthropic documents Fable as next-generation long-running agent "
            "intelligence at about 2x Opus 5 token prices. 5.1 cache-read is "
            "$0.25; this record keeps the 5.0 $1 hit rate as default."
        ),
        api_price=claude_price(
            input_usd=10.0,
            output_usd=50.0,
            cache_read=1.0,
            cache_write=12.50,
            cache_write_long=20.0,
            conditions="Fable 5.1 cache hits are $0.25 (0.025x), not $1.",
        ),
        subscription_rules=(CLAUDE_MAX_RULE, CURSOR_OTHER_RULE),
        source_urls=(ANTHROPIC_PRICING, CURSOR_PRICING),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="gpt-5.6-sol",
        provider="openai",
        display_name="GPT-5.6 Sol",
        proposed_tier="tier1",
        tier_evidence="Codex CLI documented flagship in the 5.6 family.",
        api_price=ApiPrice(
            input_per_million_usd=4.0,
            output_per_million_usd=20.0,
            cache_read_per_million_usd=0.4,
            cache_write_per_million_usd=5.0,
            cache_write_long_per_million_usd=None,
            conditions=(
                "Cursor Other Models list; promotional through 2026-11-21. "
                "Fast and long-context (>272k) are 2x. Cache writes 1.25x."
            ),
            source_url=CURSOR_PRICING,
            checked_at=CHECKED_AT,
        ),
        subscription_rules=(CODEX_PRO_RULE, CURSOR_OTHER_RULE),
        source_urls=(CURSOR_PRICING, CODEX_PRO_PLAN),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="gpt-5.6-terra",
        provider="openai",
        display_name="GPT-5.6 Terra",
        proposed_tier="tier2",
        tier_evidence="Codex CLI documented mid-tier between Sol and Luna.",
        api_price=ApiPrice(
            input_per_million_usd=2.0,
            output_per_million_usd=12.0,
            cache_read_per_million_usd=0.2,
            cache_write_per_million_usd=2.5,
            cache_write_long_per_million_usd=None,
            conditions="Cursor Other Models list. Fast and long-context 2x.",
            source_url=CURSOR_PRICING,
            checked_at=CHECKED_AT,
        ),
        subscription_rules=(CODEX_PRO_RULE, CURSOR_OTHER_RULE),
        source_urls=(CURSOR_PRICING, CODEX_PRO_PLAN),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="gpt-5.6-luna",
        provider="openai",
        display_name="GPT-5.6 Luna",
        proposed_tier="tier2",
        tier_evidence="Smallest 5.6 variant; bounded work, not demanding tasks.",
        api_price=ApiPrice(
            input_per_million_usd=0.2,
            output_per_million_usd=1.2,
            cache_read_per_million_usd=0.02,
            cache_write_per_million_usd=0.25,
            cache_write_long_per_million_usd=None,
            conditions="Cursor Other Models list. Fast and long-context 2x.",
            source_url=CURSOR_PRICING,
            checked_at=CHECKED_AT,
        ),
        subscription_rules=(CODEX_PRO_RULE, CURSOR_OTHER_RULE),
        source_urls=(CURSOR_PRICING, CODEX_PRO_PLAN),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="gpt-5.5",
        provider="openai",
        display_name="GPT-5.5",
        proposed_tier="tier1",
        tier_provisional=True,
        tier_evidence="Documented Codex CLI prior flagship; 5.6 Sol is current.",
        api_price=ApiPrice(
            input_per_million_usd=5.0,
            output_per_million_usd=30.0,
            cache_read_per_million_usd=0.5,
            cache_write_per_million_usd=None,
            cache_write_long_per_million_usd=None,
            conditions="Cursor Other Models list. Cache-write rate unpublished.",
            source_url=CURSOR_PRICING,
            checked_at=CHECKED_AT,
        ),
        subscription_rules=(CODEX_PRO_RULE, CURSOR_OTHER_RULE),
        source_urls=(CURSOR_PRICING, CODEX_PRO_PLAN),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="gpt-5.4",
        provider="openai",
        display_name="GPT-5.4",
        proposed_tier="tier2",
        tier_evidence="Documented Codex CLI prior flagship; still listed.",
        api_price=ApiPrice(
            input_per_million_usd=2.5,
            output_per_million_usd=15.0,
            cache_read_per_million_usd=0.25,
            cache_write_per_million_usd=None,
            cache_write_long_per_million_usd=None,
            conditions="Cursor Other Models list. Cache-write rate unpublished.",
            source_url=CURSOR_PRICING,
            checked_at=CHECKED_AT,
        ),
        subscription_rules=(CODEX_PRO_RULE, CURSOR_OTHER_RULE),
        source_urls=(CURSOR_PRICING, CODEX_PRO_PLAN),
        checked_at=CHECKED_AT,
    ),
)

MODEL_RECORDS: tuple[ModelRecord, ...] = CURSOR_RECORDS + _PROVIDER_RECORDS
