"""Cursor first-party records for the sourced model reference."""

from __future__ import annotations

from yoke_contracts.model_reference_records import ModelRecord
from yoke_contracts.model_reference_sources import (
    CHECKED_AT,
    CURSOR_MODELS_RULE,
    CURSOR_PRICING,
    GROK_46_DOCS,
    GROK_47_DOCS,
    REFRESHED_AT,
    cursor_pool_price,
)

CURSOR_RECORDS: tuple[ModelRecord, ...] = (
    ModelRecord(
        model_id="cursor-grok-4.7",
        provider="cursor",
        display_name="Grok 4.7",
        aliases=("grok-4.7",),
        api_price=cursor_pool_price(
            input_usd=2.0,
            cache_read=0.5,
            output_usd=6.0,
            conditions=(
                "Standard pool rate. Fast is $4/$1/$12; 500k context is "
                "$4/$1/$12, or $6/$1.5/$18 with Fast."
            ),
            checked_at=REFRESHED_AT,
        ),
        subscription_rules=(CURSOR_MODELS_RULE,),
        source_urls=(CURSOR_PRICING, GROK_47_DOCS),
        checked_at=REFRESHED_AT,
    ),
    ModelRecord(
        model_id="cursor-grok-4.6",
        provider="cursor",
        display_name="Grok 4.6",
        aliases=("grok-4.6",),
        api_price=cursor_pool_price(
            input_usd=2.0,
            cache_read=0.5,
            output_usd=6.0,
            conditions="Standard pool rate. Fast variant is 2x ($4/$1/$12).",
        ),
        subscription_rules=(CURSOR_MODELS_RULE,),
        source_urls=(CURSOR_PRICING, GROK_46_DOCS),
        checked_at=REFRESHED_AT,
    ),
    ModelRecord(
        model_id="cursor-grok-4.5",
        provider="cursor",
        display_name="Grok 4.5",
        aliases=("grok-4.5",),
        replacement_model_id="cursor-grok-4.6",
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
