"""Project-configured Pulumi ComponentResource type compatibility."""

from __future__ import annotations

from typing import Tuple

import pulumi


def component_type_aliases(stack_kind: str) -> Tuple[str, ...]:
    """Return the legacy type aliases Yoke supplies for one stack kind.

    Yoke holds them on the project's ``pulumi-state`` capability and passes
    them as ``yoke:component_type_aliases_json``; a changed alias replaces
    resources, so the program reads them as given and invents none.
    """
    raw = pulumi.Config("yoke").get_object("component_type_aliases_json")
    raw = {} if raw is None else raw
    if not isinstance(raw, dict):
        raise pulumi.RunError("yoke:component_type_aliases_json must be an object")
    aliases = raw.get(stack_kind, [])
    if not isinstance(aliases, list) or any(
        not isinstance(value, str) or not value.strip() for value in aliases
    ):
        raise pulumi.RunError(
            f"yoke:component_type_aliases_json.{stack_kind} must be a string array"
        )
    return tuple(value.strip() for value in aliases)


__all__ = ["component_type_aliases"]
