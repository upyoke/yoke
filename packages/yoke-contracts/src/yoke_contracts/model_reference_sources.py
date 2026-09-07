"""Shared sources, dates, and price helpers for the model-reference seed."""

from __future__ import annotations

from yoke_contracts.model_reference import ApiPrice, SubscriptionRule

CHECKED_AT = "2026-09-07"
ANTHROPIC_PRICING = "https://platform.claude.com/docs/en/about-claude/pricing"
CURSOR_PRICING = "https://cursor.com/docs/models-and-pricing"
GROK_46_DOCS = "https://cursor.com/docs/models/grok-4-6"
CLAUDE_MAX_PLAN = "https://support.claude.com/en/articles/11049741-what-is-the-max-plan"
CODEX_PRO_PLAN = "https://help.openai.com/en/articles/9793128-about-chatgpt-pro-tiers"

CLAUDE_MAX_RULE = SubscriptionRule(
    harness="claude",
    plan="max-20x",
    pool="included",
    rule=(
        "Max 20x ($200/mo) is 20x Pro usage per 5-hour session, plus weekly "
        "all-models and Sonnet-scoped weekly caps. Extra usage credits bill "
        "at API rates. Exact token-to-percent conversion is unpublished."
    ),
    source_url=CLAUDE_MAX_PLAN,
    checked_at=CHECKED_AT,
)
CODEX_PRO_RULE = SubscriptionRule(
    harness="codex",
    plan="pro-20x",
    pool="included",
    rule=(
        "ChatGPT Pro $200 is 20x Plus Codex usage, token-metered across a "
        "rolling 5-hour window and a weekly cap shared by CLI/IDE/cloud. "
        "Credits after included usage. Exact conversion is unpublished."
    ),
    source_url=CODEX_PRO_PLAN,
    checked_at=CHECKED_AT,
)
CURSOR_MODELS_RULE = SubscriptionRule(
    harness="cursor",
    plan="ultra",
    pool="cursor-models",
    rule=(
        "Ultra ($200/mo) includes the Cursor Models pool (Grok 4.6, Grok 4.5, "
        "Composer 2.5) with generous included usage. API dollars are not a "
        "percentage of that pool."
    ),
    source_url=CURSOR_PRICING,
    checked_at=CHECKED_AT,
)
CURSOR_OTHER_RULE = SubscriptionRule(
    harness="cursor",
    plan="ultra",
    pool="other-models",
    rule=(
        "Ultra includes $400/mo Other Models usage at each model's API rate, "
        "then on-demand at the same rates. Requests are not downgraded."
    ),
    source_url=CURSOR_PRICING,
    checked_at=CHECKED_AT,
)


def claude_price(
    *,
    input_usd: float,
    output_usd: float,
    cache_read: float,
    cache_write: float,
    cache_write_long: float,
    conditions: str,
) -> ApiPrice:
    return ApiPrice(
        input_per_million_usd=input_usd,
        output_per_million_usd=output_usd,
        cache_read_per_million_usd=cache_read,
        cache_write_per_million_usd=cache_write,
        cache_write_long_per_million_usd=cache_write_long,
        conditions=conditions,
        source_url=ANTHROPIC_PRICING,
        checked_at=CHECKED_AT,
    )


def cursor_pool_price(
    *, input_usd: float, cache_read: float, output_usd: float, conditions: str
) -> ApiPrice:
    return ApiPrice(
        input_per_million_usd=input_usd,
        output_per_million_usd=output_usd,
        cache_read_per_million_usd=cache_read,
        cache_write_per_million_usd=None,
        cache_write_long_per_million_usd=None,
        conditions=conditions,
        source_url=CURSOR_PRICING,
        checked_at=CHECKED_AT,
    )
