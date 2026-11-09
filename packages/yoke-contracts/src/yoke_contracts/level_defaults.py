"""Operator-approved current-model minimum-effort bands."""


def _entry(model, effort):
    return {"model": model, "min_effort": effort}


DEFAULT_LEVELS = (
    {
        "name": "INTERN",
        "glyph": "🐣",
        "options": [
            _entry("claude-haiku-5-5", "low"),
            _entry("gpt-6-luna", "low"),
            _entry("claude-sonnet-5-5", "low"),
            _entry("gpt-6.1-terra", "low"),
            _entry("grok-4.7", "low"),
        ],
    },
    {
        "name": "JUNIOR",
        "glyph": "🐥",
        "options": [
            _entry("grok-4.7", "high"),
            _entry("gpt-6.1-terra", "high"),
            _entry("claude-sonnet-5-5", "high"),
            _entry("claude-opus-5-5", "low"),
            _entry("gpt-6.1-sol", "low"),
            _entry("claude-fable-5-2", "low"),
            _entry("gpt-6-astra", "low"),
        ],
    },
    {
        "name": "SENIOR",
        "glyph": "🦉",
        "options": [
            _entry("claude-opus-5-5", "medium"),
            _entry("gpt-6.1-sol", "medium"),
            _entry("claude-fable-5-2", "medium"),
            _entry("gpt-6-astra", "medium"),
        ],
    },
    {
        "name": "PRINCIPAL",
        "glyph": "🦅",
        "options": [
            _entry("claude-fable-5-2", "xhigh"),
            _entry("gpt-6-astra", "xhigh"),
        ],
    },
)

__all__ = ["DEFAULT_LEVELS"]
