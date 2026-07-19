"""Small, deterministic placeholder renderer for immutable Pack versions."""

from __future__ import annotations

from collections.abc import Mapping


def render_pack_text(content: str, values: Mapping[str, str]) -> str:
    """Replace ``{{name}}`` tokens without interpreting GitHub expressions."""

    rendered = content
    for key in sorted(values, key=len, reverse=True):
        rendered = rendered.replace(f"{{{{{key}}}}}", values[key])
    return rendered


__all__ = ["render_pack_text"]
