"""GPT-6.1 records for the sourced model reference."""

from __future__ import annotations

from yoke_contracts.model_reference import validate_model_record
from yoke_contracts.model_reference_records import ModelRecord

GPT61_RECORDS: tuple[ModelRecord, ...] = (
    validate_model_record(
        {
            "aliases": [],
            "api_price": {
                "cache_read_per_million_usd": 0.1,
                "cache_write_long_per_million_usd": 5.0,
                "cache_write_per_million_usd": 2.5,
                "checked_at": "2026-11-09",
                "conditions": "Standard rate. Cached input bills at 5% of the uncached input rate. Cache write $2.50 is 30-minute retention; 12-hour write $5.00. API prompts over 272K input bill at 2x input and cache rates and 1.5x output. Batch and Flex are 50%; Fast is 2x; Ultrafast is 6x. Regional processing adds a 10% premium where available. Codex and ChatGPT Work default to a 500K context window with no long-context surcharge on subscription usage.",
                "effective_at": None,
                "estimate_basis": None,
                "estimated_fields": [],
                "input_per_million_usd": 2.0,
                "output_per_million_usd": 10.0,
                "source_url": "https://developers.openai.com/api/docs/pricing"
            },
            "benchmarks": [],
            "checked_at": "2026-10-12",
            "context_window_tokens": [
                1050000
            ],
            "display_name": "GPT-6.1 Sol",
            "model_id": "gpt-6.1-sol",
            "operator_notes": None,
            "provider": "openai",
            "reasoning_efforts": [
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
                "ultra"
            ],
            "replacement_model_id": None,
            "source_urls": [
                "https://developers.openai.com/api/docs/models/gpt-6.1-sol",
                "https://learn.chatgpt.com/docs/pricing",
                "https://developers.openai.com/api/docs/guides/latest-model"
            ],
            "subscription_rules": [
                {
                    "checked_at": "2026-09-29",
                    "consumption_weight": {
                        "cached_input_per_million": 2.5,
                        "checked_at": "2026-09-29",
                        "estimate_basis": None,
                        "input_per_million": 50.0,
                        "is_estimate": False,
                        "output_per_million": 250.0,
                        "source_url": "https://learn.chatgpt.com/docs/pricing",
                        "unit": "credits"
                    },
                    "estimate_basis": None,
                    "harness": "codex",
                    "is_estimate": False,
                    "plan": "pro",
                    "pool": "included",
                    "rule": "ChatGPT meters plan usage in credits at a published per-model rate; local CLI messages and cloud chats share one plan allowance. Reaching the limit allows purchasing further credits. No credit-to-included-percent conversion is published, and message ranges vary with task size.",
                    "source_url": "https://learn.chatgpt.com/docs/pricing"
                }
            ]
        }
    ),
    validate_model_record(
        {
            "aliases": [],
            "api_price": {
                "cache_read_per_million_usd": 0.05,
                "cache_write_long_per_million_usd": 2.5,
                "cache_write_per_million_usd": 1.25,
                "checked_at": "2026-11-09",
                "conditions": "Standard rate. Cached input bills at 5% of the uncached input rate. Cache write $1.25 is 30-minute retention; 12-hour write $2.50. Prompts over 272K input bill at 2x input and cache rates and 1.5x output. Batch and Flex are 50%; Fast is 2x. Regional processing adds a 10% premium where available. No Ultrafast pricing published.",
                "effective_at": "2026-10-26",
                "estimate_basis": None,
                "estimated_fields": [],
                "input_per_million_usd": 1.0,
                "output_per_million_usd": 5.0,
                "source_url": "https://developers.openai.com/api/docs/models/gpt-6.1-terra"
            },
            "benchmarks": [],
            "checked_at": "2026-11-09",
            "context_window_tokens": [
                1050000
            ],
            "display_name": "GPT-6.1 Terra",
            "model_id": "gpt-6.1-terra",
            "operator_notes": None,
            "provider": "openai",
            "reasoning_efforts": [
                "none",
                "low",
                "medium",
                "high",
                "xhigh",
                "max"
            ],
            "replacement_model_id": None,
            "source_urls": [
                "https://developers.openai.com/api/docs/models/gpt-6.1-terra",
                "https://learn.chatgpt.com/docs/pricing",
                "https://developers.openai.com/api/docs/guides/latest-model",
                "https://developers.openai.com/api/docs/pricing"
            ],
            "subscription_rules": [
                {
                    "checked_at": "2026-11-09",
                    "consumption_weight": {
                        "cached_input_per_million": 1.25,
                        "checked_at": "2026-11-09",
                        "estimate_basis": None,
                        "input_per_million": 25.0,
                        "is_estimate": False,
                        "output_per_million": 125.0,
                        "source_url": "https://learn.chatgpt.com/docs/pricing",
                        "unit": "credits"
                    },
                    "estimate_basis": None,
                    "harness": "codex",
                    "is_estimate": False,
                    "plan": "pro",
                    "pool": "included",
                    "rule": "ChatGPT meters plan usage in credits at a published per-model rate; local CLI messages and cloud chats share one plan allowance. Reaching the limit allows purchasing further credits. No credit-to-included-percent conversion is published, and message ranges vary with task size.",
                    "source_url": "https://learn.chatgpt.com/docs/pricing"
                }
            ]
        }
    ),
)
