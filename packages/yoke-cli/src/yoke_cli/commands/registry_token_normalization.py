"""Natural space-separated token routing derived from primary commands."""

from __future__ import annotations

from typing import Dict, Mapping, Tuple, TypeVar


RegistryEntry = TypeVar("RegistryEntry")


def expanded_hyphen_routes(
    primary: Mapping[Tuple[str, ...], RegistryEntry],
    established_routes: Mapping[Tuple[str, ...], RegistryEntry],
    *,
    split_leaf: bool = True,
) -> Dict[Tuple[str, ...], RegistryEntry]:
    """Normalize spaces inside hyphenated tokens without adding stored aliases.

    ``split_leaf=False`` splits only group tokens (``github actions poll``),
    the spellings help lists; a split leaf (``sessions end if empty``) still
    resolves when typed but is never a group of its own.
    """
    normalized: Dict[Tuple[str, ...], RegistryEntry] = {}
    for tokens, entry in (*primary.items(), *established_routes.items()):
        split = tokens if split_leaf else tokens[:-1]
        expanded = tuple(part for token in split for part in token.split("-"))
        expanded += () if split_leaf else tokens[-1:]
        if expanded != tokens and expanded not in primary:
            normalized.setdefault(expanded, entry)
    return normalized


def spaced_routes(
    primary: Mapping[Tuple[str, ...], RegistryEntry],
    established_routes: Mapping[Tuple[str, ...], RegistryEntry],
) -> Tuple[Dict[Tuple[str, ...], RegistryEntry], Dict[Tuple[str, ...], RegistryEntry]]:
    """Return the listed group-split spellings and every spelling that resolves."""
    groups = expanded_hyphen_routes(primary, established_routes, split_leaf=False)
    return groups, {**groups, **expanded_hyphen_routes(primary, established_routes)}


__all__ = ["expanded_hyphen_routes", "spaced_routes"]
