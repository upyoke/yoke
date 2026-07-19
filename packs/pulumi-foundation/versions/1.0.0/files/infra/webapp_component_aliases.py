"""Project-configured Pulumi ComponentResource type compatibility."""

from __future__ import annotations

from typing import Tuple

import pulumi


def component_type_aliases(stack_kind: str) -> Tuple[str, ...]:
    """Return legacy type aliases declared for one rendered stack kind."""
    raw = pulumi.Config().get_object("component_type_aliases")
    raw = {} if raw is None else raw
    if not isinstance(raw, dict):
        raise pulumi.RunError("component_type_aliases must be an object")
    aliases = raw.get(stack_kind, [])
    if not isinstance(aliases, list) or any(
        not isinstance(value, str) or not value.strip() for value in aliases
    ):
        raise pulumi.RunError(
            f"component_type_aliases.{stack_kind} must be a string array"
        )
    return tuple(value.strip() for value in aliases)


__all__ = ["component_type_aliases"]
