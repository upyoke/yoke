"""Pure routing-state interpretation for self-hosted Actions runners."""

from __future__ import annotations

from typing import Sequence

from yoke_core.domain import json_helper


def routing_matches(value: str | None, required: Sequence[str]) -> bool:
    """Return whether the repo variable semantically names the required labels."""
    if not value:
        return False
    try:
        parsed = json_helper.loads_text(value)
    except (TypeError, ValueError):
        return False
    if not isinstance(parsed, list):
        return False
    labels = [item.strip().casefold() for item in parsed if isinstance(item, str)]
    expected = [item.strip().casefold() for item in required]
    return (
        len(labels) == len(parsed) == len(expected)
        and all(labels)
        and set(labels) == set(expected)
    )



__all__ = ["routing_matches"]
