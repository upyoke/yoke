"""Shared sources, dates, and price helpers for the model-reference seed."""

from __future__ import annotations

from yoke_contracts.model_reference_records import (
    ApiPrice,
    ConsumptionWeight,
    SubscriptionRule,
)

CHECKED_AT = "2026-09-07"
ANTHROPIC_PRICING = "https://platform.claude.com/docs/en/about-claude/pricing"
CURSOR_PRICING = "https://cursor.com/docs/models-and-pricing"
GROK_46_DOCS = "https://cursor.com/docs/models/grok-4-6"
CLAUDE_MAX_PLAN = "https://support.claude.com/en/articles/11049741-what-is-the-max-plan"
CODEX_PRO_PLAN = "https://help.openai.com/en/articles/9793128-about-chatgpt-pro-tiers"
CHATGPT_PRICING = "https://learn.chatgpt.com/docs/pricing"
OPENAI_MODEL_DOCS = "https://developers.openai.com/api/docs/models"
OPENROUTER_ASTRA = "https://openrouter.ai/openai/gpt-6-astra"

#: The unit ChatGPT meters plan usage in. Credits are not dollars and the
#: page publishes no conversion from credits to a percentage of an included
#: allowance, so they stay a consumption weight rather than a price.
CHATGPT_CREDIT_UNIT = "credits"

CLAUDE_MAX_RULE = SubscriptionRule(
    harness="claude",
    plan="max-20x",
    pool="included",
    rule=(
        "Max 20x provides 20 times more usage per session than Pro, on a "
        "five-hour session window, plus a weekly limit that applies across "
        "all models. No token-to-percent conversion is published, and the "
        "page reserves further discretionary limiting."
    ),
    source_url=CLAUDE_MAX_PLAN,
    checked_at=CHECKED_AT,
)
CURSOR_MODELS_RULE = SubscriptionRule(
    harness="cursor",
    plan="ultra",
    pool="cursor-models",
    rule=(
        "Ultra includes the Cursor Models pool (Grok 4.6, Grok 4.5, "
        "Composer 2.5). The included monthly amount is not published; the "
        "account usage dashboard is the only reading of what remains. API "
        "dollars are not a percentage of that pool."
    ),
    source_url=CURSOR_PRICING,
    checked_at=CHECKED_AT,
)
CURSOR_OTHER_RULE = SubscriptionRule(
    harness="cursor",
    plan="ultra",
    pool="other-models",
    rule=(
        "Ultra includes Other Models usage charged at each model's API "
        "price, then on-demand at the same rates. Requests are not "
        "downgraded. The included monthly amount is not published."
    ),
    source_url=CURSOR_PRICING,
    checked_at=CHECKED_AT,
)


def chatgpt_credits(
    *, input_credits: float, cached_input_credits: float, output_credits: float
) -> ConsumptionWeight:
    """One model's published ChatGPT credit weight per million tokens."""
    return ConsumptionWeight(
        unit=CHATGPT_CREDIT_UNIT,
        input_per_million=input_credits,
        cached_input_per_million=cached_input_credits,
        output_per_million=output_credits,
        source_url=CHATGPT_PRICING,
        checked_at=CHECKED_AT,
    )


def codex_pro_rule(weight: ConsumptionWeight | None = None) -> SubscriptionRule:
    """The ChatGPT plan rule Codex CLI work consumes, with its credit weight.

    The weight is what the plan meters; how many credits a plan includes,
    and therefore what share of an allowance a session spends, is not
    published. A model with no published weight passes ``None`` rather than
    borrowing another model's.
    """
    return SubscriptionRule(
        harness="codex",
        plan="pro",
        pool="included",
        rule=(
            "ChatGPT meters plan usage in credits at a published per-model "
            "rate; local CLI messages and cloud chats share one plan "
            "allowance. Reaching the limit allows purchasing further "
            "credits. No credit-to-included-percent conversion is "
            "published, and message ranges vary with task size."
        ),
        source_url=CHATGPT_PRICING,
        checked_at=CHECKED_AT,
        consumption_weight=weight,
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


#: The multiple of the base input rate that the GPT-5.6 family's published
#: cache-write prices sit at on the Cursor Other Models list ($4 → $5,
#: $2 → $2.50, $0.20 → $0.25). Older listings publish no cache-write rate,
#: so this is the basis for the labelled estimate that fills them.
CURSOR_CACHE_WRITE_MULTIPLE = 1.25
CURSOR_CACHE_WRITE_ESTIMATE_BASIS = (
    "The Cursor Other Models list publishes no cache-write rate for this "
    "model. Every GPT-5.6 entry on the same list writes at 1.25x its base "
    "input rate ($4 to $5, $2 to $2.50, $0.20 to $0.25), so the estimate is "
    "1.25x input. Replace it with the published rate if one appears."
)


def cursor_other_price(
    *,
    input_usd: float,
    cache_read: float,
    output_usd: float,
    conditions: str,
    cache_write_usd: float | None = None,
) -> ApiPrice:
    """Price one Other Models entry, estimating an unpublished cache write.

    Passing ``cache_write_usd`` records a published rate. Omitting it fills
    the field from ``CURSOR_CACHE_WRITE_MULTIPLE`` and labels that one field
    an estimate, so a reader can tell the inferred rate from the listed ones
    rather than seeing a gap where the cost readers would price nothing.
    """
    if cache_write_usd is not None:
        return ApiPrice(
            input_per_million_usd=input_usd,
            output_per_million_usd=output_usd,
            cache_read_per_million_usd=cache_read,
            cache_write_per_million_usd=cache_write_usd,
            conditions=conditions,
            source_url=CURSOR_PRICING,
            checked_at=CHECKED_AT,
        )
    return ApiPrice(
        input_per_million_usd=input_usd,
        output_per_million_usd=output_usd,
        cache_read_per_million_usd=cache_read,
        cache_write_per_million_usd=round(input_usd * CURSOR_CACHE_WRITE_MULTIPLE, 4),
        conditions=conditions,
        source_url=CURSOR_PRICING,
        checked_at=CHECKED_AT,
        estimated_fields=("cache_write_per_million_usd",),
        estimate_basis=CURSOR_CACHE_WRITE_ESTIMATE_BASIS,
    )
