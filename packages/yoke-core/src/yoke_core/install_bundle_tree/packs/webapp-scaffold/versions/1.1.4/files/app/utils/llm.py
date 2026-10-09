"""LLM client utilities for {{project_display_name}}.

Provides an Anthropic API client wrapper. The API key is optional —
a RuntimeError is raised only when get_client() is called without
ANTHROPIC_API_KEY set.
"""

import os


def get_client():
    """Initialize Anthropic client from ANTHROPIC_API_KEY env var.

    Returns:
        (client, None) on success.
        (None, error_string) on failure.

    Raises:
        RuntimeError: If ANTHROPIC_API_KEY is not set.
    """
    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "anthropic package not installed. Run: pip install anthropic"
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable not set. "
            "Set it in your .env file or environment to use LLM features."
        )

    return anthropic.Anthropic(api_key=api_key), None
