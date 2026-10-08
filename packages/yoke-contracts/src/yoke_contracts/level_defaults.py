"""The shipped execution-level scheme: INTERN < JUNIOR < SENIOR < PRINCIPAL.

Every universe reads this scheme until an operator stores its own with
``yoke universe levels set``. The options are the operator-approved starting
selections, each level's options in order; :func:`yoke_contracts.levels.parse_levels`
validates them like any stored document.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


def _option(surface: str, model: str, effort: str, context: Optional[int] = None):
    return {
        "surface": surface,
        "model": model,
        "reasoning_effort": effort,
        "context_window_tokens": context,
    }


#: The shipped scheme every universe reads until an operator stores its own:
#: the operator-approved starting options, each level's options in order.
DEFAULT_LEVELS: tuple[Mapping[str, Any], ...] = (
    {
        "name": "INTERN",
        "glyph": "\U0001f423",
        "options": [
            _option("claude-cli", "claude-haiku-4-5", "max"),
            _option("codex-cli", "gpt-6-luna", "max"),
        ],
    },
    {
        "name": "JUNIOR",
        "glyph": "\U0001f425",
        "options": [
            {
                **_option("cursor-cli", "grok-4.7-high", "high"),
                "fallback": _option("cursor-cli", "claude-opus-5-5-medium", "medium"),
            },
            _option("codex-cli", "gpt-5.6-terra", "xhigh"),
            _option("claude-cli", "claude-sonnet-5-5", "xhigh", 1_000_000),
        ],
    },
    {
        "name": "SENIOR",
        "glyph": "\U0001f989",
        "options": [
            _option("claude-cli", "claude-opus-5-5", "medium", 1_000_000),
            _option("codex-cli", "gpt-6.1-sol", "medium"),
        ],
    },
    {
        "name": "PRINCIPAL",
        "glyph": "\U0001f985",
        "options": [
            _option("claude-cli", "claude-fable-5-1", "xhigh", 1_000_000),
            _option("codex-cli", "gpt-6-astra", "xhigh"),
        ],
    },
)


__all__ = ["DEFAULT_LEVELS"]
