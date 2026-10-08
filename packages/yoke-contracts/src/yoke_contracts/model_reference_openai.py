"""OpenAI records for the sourced model reference."""

from __future__ import annotations

from yoke_contracts.model_reference_records import ApiPrice, ModelRecord
from yoke_contracts.model_reference_sources import (
    CHATGPT_PRICING,
    CHECKED_AT,
    CODEX_PRO_PLAN,
    CURSOR_OTHER_RULE,
    CURSOR_PRICING,
    OPENAI_MODEL_DOCS,
    REFRESHED_AT,
    chatgpt_credits,
    codex_pro_rule,
    cursor_other_price,
)

_ASTRA_DOCS = f"{OPENAI_MODEL_DOCS}/gpt-6-astra"
_SOL_DOCS = f"{OPENAI_MODEL_DOCS}/gpt-6-sol"
_LUNA_DOCS = f"{OPENAI_MODEL_DOCS}/gpt-6-luna"

OPENAI_RECORDS: tuple[ModelRecord, ...] = (
    ModelRecord(
        model_id="gpt-6-astra",
        provider="openai",
        display_name="GPT-6 Astra",
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
        source_urls=(_ASTRA_DOCS, CHATGPT_PRICING),
        checked_at=CHECKED_AT,
    ),
    ModelRecord(
        model_id="gpt-6-sol",
        provider="openai",
        display_name="GPT-6 Sol",
        api_price=ApiPrice(
            input_per_million_usd=2.0,
            output_per_million_usd=10.0,
            cache_read_per_million_usd=0.20,
            cache_write_per_million_usd=2.50,
            conditions=(
                "Standard rate. Prompts over 272K input bill at 2x input and "
                "cache rates and 1.5x output. Batch and Flex are 50%; Fast is 2x."
            ),
            source_url=_SOL_DOCS,
            checked_at=REFRESHED_AT,
        ),
        subscription_rules=(
            codex_pro_rule(
                chatgpt_credits(
                    input_credits=50.0,
                    cached_input_credits=5.0,
                    output_credits=250.0,
                    checked_at=REFRESHED_AT,
                ),
                checked_at=REFRESHED_AT,
            ),
        ),
        source_urls=(_SOL_DOCS, CHATGPT_PRICING),
        checked_at=REFRESHED_AT,
    ),
    ModelRecord(
        model_id="gpt-6-luna",
        provider="openai",
        display_name="GPT-6 Luna",
        api_price=ApiPrice(
            input_per_million_usd=0.10,
            output_per_million_usd=0.50,
            cache_read_per_million_usd=0.01,
            cache_write_per_million_usd=0.125,
            conditions=(
                "Standard rate. Prompts over 272K input bill at 2x input and "
                "cache rates and 1.5x output. Batch and Flex are 50%; Fast is 2x."
            ),
            source_url=_LUNA_DOCS,
            checked_at=REFRESHED_AT,
        ),
        subscription_rules=(
            codex_pro_rule(
                chatgpt_credits(
                    input_credits=2.5,
                    cached_input_credits=0.25,
                    output_credits=12.5,
                    checked_at=REFRESHED_AT,
                ),
                checked_at=REFRESHED_AT,
            ),
        ),
        source_urls=(_LUNA_DOCS, CHATGPT_PRICING),
        checked_at=REFRESHED_AT,
    ),
    ModelRecord(
        model_id="gpt-5.6-sol",
        provider="openai",
        display_name="GPT-5.6 Sol",
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
        checked_at=REFRESHED_AT,
    ),
    ModelRecord(
        model_id="gpt-5.6-terra",
        provider="openai",
        display_name="GPT-5.6 Terra",
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
