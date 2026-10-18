"""OpenAI records for the sourced model reference."""

from __future__ import annotations

from yoke_contracts.model_reference import validate_model_record

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
    validate_model_record(
        {
            "aliases": [],
            "api_price": {
                "cache_read_per_million_usd": 0.1,
                "cache_write_long_per_million_usd": None,
                "cache_write_per_million_usd": 2.5,
                "checked_at": "2026-09-29",
                "conditions": "Standard rate. Cached input bills at 5% of the uncached input rate. Prompts over 272K input bill at 2x input and cache rates and 1.5x output. Batch and Flex are 50%; Fast is 2x. Regional processing adds a 10% premium where available.",
                "effective_at": None,
                "estimate_basis": None,
                "estimated_fields": [],
                "input_per_million_usd": 2,
                "output_per_million_usd": 10,
                "source_url": "https://developers.openai.com/api/docs/models/gpt-6.1-sol",
            },
            "benchmarks": [],
            "checked_at": "2026-10-12",
            "context_window_tokens": [],
            "display_name": "GPT-6.1 Sol",
            "model_id": "gpt-6.1-sol",
            "operator_notes": None,
            "provider": "openai",
            "reasoning_efforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
            "replacement_model_id": None,
            "source_urls": [
                "https://developers.openai.com/api/docs/models/gpt-6.1-sol",
                "https://learn.chatgpt.com/docs/pricing",
                "https://developers.openai.com/api/docs/guides/latest-model",
            ],
            "subscription_rules": [
                {
                    "checked_at": "2026-09-29",
                    "consumption_weight": {
                        "cached_input_per_million": 2.5,
                        "checked_at": "2026-09-29",
                        "estimate_basis": None,
                        "input_per_million": 50,
                        "is_estimate": False,
                        "output_per_million": 250,
                        "source_url": "https://learn.chatgpt.com/docs/pricing",
                        "unit": "credits",
                    },
                    "estimate_basis": None,
                    "harness": "codex",
                    "is_estimate": False,
                    "plan": "pro",
                    "pool": "included",
                    "rule": "ChatGPT meters plan usage in credits at a published per-model rate; local CLI messages and cloud chats share one plan allowance. Reaching the limit allows purchasing further credits. No credit-to-included-percent conversion is published, and message ranges vary with task size.",
                    "source_url": "https://learn.chatgpt.com/docs/pricing",
                }
            ],
        }
    ),
    ModelRecord(
        model_id="gpt-6-astra",
        reasoning_efforts=(
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
        ),
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
        checked_at="2026-10-12",
    ),
    ModelRecord(
        model_id="gpt-6-sol",
        reasoning_efforts=(
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
        ),
        replacement_model_id="gpt-6.1-sol",
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
        checked_at="2026-10-12",
    ),
    ModelRecord(
        model_id="gpt-6-luna",
        reasoning_efforts=(
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ),
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
        checked_at="2026-10-12",
    ),
    ModelRecord(
        model_id="gpt-5.6-sol",
        reasoning_efforts=(
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
        ),
        replacement_model_id="gpt-6.1-sol",
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
        checked_at="2026-10-12",
    ),
    ModelRecord(
        model_id="gpt-5.6-terra",
        reasoning_efforts=(
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
        ),
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
        checked_at="2026-10-12",
    ),
    ModelRecord(
        model_id="gpt-5.6-luna",
        reasoning_efforts=(
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ),
        replacement_model_id="gpt-6-luna",
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
        checked_at="2026-10-12",
    ),
    ModelRecord(
        model_id="gpt-5.5",
        reasoning_efforts=(
            "none",
            "low",
            "medium",
            "high",
            "extra-high",
        ),
        replacement_model_id="gpt-6.1-sol",
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
        checked_at="2026-10-12",
    ),
    ModelRecord(
        model_id="gpt-5.4",
        reasoning_efforts=(
            "low",
            "medium",
            "high",
            "xhigh",
        ),
        replacement_model_id="gpt-5.6-terra",
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
        checked_at="2026-10-12",
    ),
)
