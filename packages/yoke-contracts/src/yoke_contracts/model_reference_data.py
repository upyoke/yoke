"""Seeded current model-reference document. Refresh by editing family modules.

Prices and subscription rules are copied from public primary sources on
CHECKED_AT. Unknown leaves stay None; an inferred rate is filled only with
its ``estimated_fields`` label and a stated basis. API dollars are not
subscription percentages: a plan's own metered weighting rides on the
subscription rule as a consumption weight and is never summed with money.
Benchmarks stay empty until a named public result is attached.
"""

from __future__ import annotations

from yoke_contracts.model_reference_cursor import CURSOR_RECORDS
from yoke_contracts.model_reference_records import ApiPrice, ModelRecord
from yoke_contracts.model_reference_sources import (
    ANTHROPIC_PRICING,
    CHATGPT_PRICING,
    CHECKED_AT,
    CLAUDE_MAX_RULE,
    CODEX_PRO_PLAN,
    CURSOR_OTHER_RULE,
    CURSOR_PRICING,
    OPENAI_MODEL_DOCS,
    OPENROUTER_ASTRA,
    chatgpt_credits,
    claude_price,
    codex_pro_rule,
    cursor_other_price,
)

#: Every OpenAI record cites the model docs entry for its own id.
_ASTRA_DOCS = f"{OPENAI_MODEL_DOCS}/gpt-6-astra"

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
        model_id="claude-fable-5-1",
        provider="anthropic",
        display_name="Claude Fable 5.1",
        aliases=("claude-fable-5.1",),
        proposed_tier="tier1",
        tier_provisional=True,
        tier_evidence=(
            "Anthropic documents Fable as next-generation long-running agent "
            "intelligence at about 2x Opus 5 token prices. 5.1 is a separate "
            "row on the pricing table because its cache hits are cheaper."
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
        tier_provisional=True,
        tier_evidence=(
            "Prior Fable release, still listed at Fable rates. Its cache hits "
            "are $1; the 5.1 row prices the same hit at $0.25."
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
    ModelRecord(
        model_id="gpt-6-astra",
        provider="openai",
        display_name="GPT-6 Astra",
        proposed_tier="tier1",
        tier_evidence=(
            "OpenAI documents Astra for demanding end-to-end work and "
            "long-horizon agentic tasks, at 2.5x the Sol input rate."
        ),
        api_price=ApiPrice(
            input_per_million_usd=10.0,
            output_per_million_usd=50.0,
            cache_read_per_million_usd=1.0,
            cache_write_per_million_usd=12.50,
            conditions=(
                "Standard rate; this reference carries no service-tier-specific "
                "pricing. Prompts over 272K input bill at 2x input and cache "
                "rates and 1.5x output. Batch and Flex are 50%; Fast is 2x."
            ),
            source_url=_ASTRA_DOCS,
            checked_at=CHECKED_AT,
        ),
        subscription_rules=(
            codex_pro_rule(
                chatgpt_credits(
                    input_credits=250.0,
                    cached_input_credits=25.0,
                    output_credits=1250.0,
                )
            ),
        ),
        source_urls=(_ASTRA_DOCS, OPENROUTER_ASTRA, CHATGPT_PRICING),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="gpt-5.6-sol",
        provider="openai",
        display_name="GPT-5.6 Sol",
        proposed_tier="tier1",
        tier_evidence="Codex CLI documented flagship in the 5.6 family.",
        api_price=cursor_other_price(
            input_usd=4.0,
            cache_read=0.4,
            cache_write_usd=5.0,
            output_usd=20.0,
            conditions=(
                "Cursor Other Models list; promotional through 2026-11-21. "
                "Fast and long-context (>272k) are 2x."
            ),
        ),
        subscription_rules=(
            codex_pro_rule(
                chatgpt_credits(
                    input_credits=100.0,
                    cached_input_credits=10.0,
                    output_credits=500.0,
                )
            ),
            CURSOR_OTHER_RULE,
        ),
        source_urls=(CURSOR_PRICING, CHATGPT_PRICING, CODEX_PRO_PLAN),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="gpt-5.6-terra",
        provider="openai",
        display_name="GPT-5.6 Terra",
        proposed_tier="tier2",
        tier_evidence="Codex CLI documented mid-tier between Sol and Luna.",
        api_price=cursor_other_price(
            input_usd=2.0,
            cache_read=0.2,
            cache_write_usd=2.5,
            output_usd=12.0,
            conditions="Cursor Other Models list. Fast and long-context 2x.",
        ),
        subscription_rules=(
            codex_pro_rule(
                chatgpt_credits(
                    input_credits=50.0,
                    cached_input_credits=5.0,
                    output_credits=300.0,
                )
            ),
            CURSOR_OTHER_RULE,
        ),
        source_urls=(CURSOR_PRICING, CHATGPT_PRICING, CODEX_PRO_PLAN),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="gpt-5.6-luna",
        provider="openai",
        display_name="GPT-5.6 Luna",
        proposed_tier="tier2",
        tier_evidence="Smallest 5.6 variant; bounded work, not demanding tasks.",
        api_price=cursor_other_price(
            input_usd=0.2,
            cache_read=0.02,
            cache_write_usd=0.25,
            output_usd=1.2,
            conditions="Cursor Other Models list. Fast and long-context 2x.",
        ),
        subscription_rules=(
            codex_pro_rule(
                chatgpt_credits(
                    input_credits=5.0,
                    cached_input_credits=0.5,
                    output_credits=30.0,
                )
            ),
            CURSOR_OTHER_RULE,
        ),
        source_urls=(CURSOR_PRICING, CHATGPT_PRICING, CODEX_PRO_PLAN),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="gpt-5.5",
        provider="openai",
        display_name="GPT-5.5",
        proposed_tier="tier1",
        tier_provisional=True,
        tier_evidence="Documented Codex CLI prior flagship; 5.6 Sol is current.",
        api_price=cursor_other_price(
            input_usd=5.0,
            cache_read=0.5,
            output_usd=30.0,
            conditions="Cursor Other Models list.",
        ),
        subscription_rules=(codex_pro_rule(), CURSOR_OTHER_RULE),
        source_urls=(CURSOR_PRICING, CHATGPT_PRICING, CODEX_PRO_PLAN),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="gpt-5.4",
        provider="openai",
        display_name="GPT-5.4",
        proposed_tier="tier2",
        tier_evidence="Documented Codex CLI prior flagship; still listed.",
        api_price=cursor_other_price(
            input_usd=2.5,
            cache_read=0.25,
            output_usd=15.0,
            conditions="Cursor Other Models list.",
        ),
        subscription_rules=(codex_pro_rule(), CURSOR_OTHER_RULE),
        source_urls=(CURSOR_PRICING, CHATGPT_PRICING, CODEX_PRO_PLAN),
        checked_at=CHECKED_AT,
    ),
)

MODEL_RECORDS: tuple[ModelRecord, ...] = CURSOR_RECORDS + _PROVIDER_RECORDS
