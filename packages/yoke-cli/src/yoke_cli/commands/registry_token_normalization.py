"""Natural space-separated token routing derived from primary commands."""

from __future__ import annotations

from typing import Dict, Mapping, Tuple, TypeVar


RegistryEntry = TypeVar("RegistryEntry")


def expanded_hyphen_routes(
    primary: Mapping[Tuple[str, ...], RegistryEntry],
    established_routes: Mapping[Tuple[str, ...], RegistryEntry],
) -> Dict[Tuple[str, ...], RegistryEntry]:
    """Normalize spaces inside hyphenated tokens without adding stored aliases."""
    normalized: Dict[Tuple[str, ...], RegistryEntry] = {}
    for tokens, entry in (*primary.items(), *established_routes.items()):
        expanded = tuple(part for token in tokens for part in token.split("-"))
        if expanded != tokens and expanded not in primary:
            normalized.setdefault(expanded, entry)
    return normalized


__all__ = ["expanded_hyphen_routes"]
