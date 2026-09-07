"""Cursor first-party records for the sourced model reference."""

from __future__ import annotations

from yoke_contracts.model_reference import ModelRecord
from yoke_contracts.model_reference_sources import (
    CHECKED_AT,
    CURSOR_MODELS_RULE,
    CURSOR_PRICING,
    GROK_46_DOCS,
    cursor_pool_price,
)

CURSOR_RECORDS: tuple[ModelRecord, ...] = (
    ModelRecord(
        model_id="cursor-grok-4.6",
        provider="cursor",
        display_name="Grok 4.6",
        aliases=("grok-4.6",),
        proposed_tier="tier1",
        tier_evidence=(
            "Cursor documents Grok 4.6 as its frontier first-party model for "
            "complex long-horizon coding. Stronger models at lower reasoning "
            "are not a blanket replacement for second-tier Sonnet."
        ),
        operator_notes=(
            "Operator routing annotation, not a published fact and not "
            "proposed_tier. Cursor tier1 is Grok 4.6; Cursor Opus is fallback "
            "only after confirmed Grok/Cursor Models quota exhaustion. "
            "Unknown/stale/error is not exhaustion. Approved 2026-09-07 "
            "reasoning defaults for future launches only: simple edits, docs, "
            "and cleanup use tier2+medium; normal development, research, and "
            "steering use tier1+high; difficult debugging or architectural "
            "decisions use tier1+xhigh (high where xhigh is unsupported). No "
            "automatic max. Per-surface routing lives in session_model_routing."
        ),
        api_price=cursor_pool_price(
            input_usd=2.0,
            cache_read=0.5,
            output_usd=6.0,
            conditions="Standard pool rate. Fast variant is 2x ($4/$1/$12).",
        ),
        subscription_rules=(CURSOR_MODELS_RULE,),
        source_urls=(CURSOR_PRICING, GROK_46_DOCS),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="cursor-grok-4.5",
        provider="cursor",
        display_name="Grok 4.5",
        aliases=("grok-4.5",),
        replacement_model_id="cursor-grok-4.6",
        proposed_tier="tier2",
        tier_evidence=(
            "Still in the Cursor Models pool; Cursor names 4.6 as the successor."
        ),
        tier_provisional=True,
        api_price=cursor_pool_price(
            input_usd=2.0,
            cache_read=0.5,
            output_usd=6.0,
            conditions="Standard pool rate. Fast variant listed at $4/$1/$18.",
        ),
        subscription_rules=(CURSOR_MODELS_RULE,),
        source_urls=(CURSOR_PRICING,),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="composer-2.5",
        provider="cursor",
        display_name="Composer 2.5",
        aliases=("cursor-composer-2.5",),
        proposed_tier="tier2",
        tier_evidence=(
            "Cursor second-tier first-party model in the Grok included pool."
        ),
        api_price=cursor_pool_price(
            input_usd=0.5,
            cache_read=0.2,
            output_usd=2.5,
            conditions="Standard pool rate. Fast variant listed at $3/$0.5/$15.",
        ),
        subscription_rules=(CURSOR_MODELS_RULE,),
        source_urls=(CURSOR_PRICING,),
        checked_at=CHECKED_AT,
    ),
)
