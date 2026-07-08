"""Normalize client-provided Git commit facts for authority checks."""

from __future__ import annotations

from typing import Mapping, Optional

from yoke_contracts.hook_runner.main_commit import (
    CLIENT_GIT_COMMIT_FACTS_KEY,
    CLIENT_GIT_COMMIT_FACTS_SCHEMA,
)


def client_facts(payload: dict) -> Optional[Mapping[str, object]]:
    """Return validated client facts from *payload*, if present."""
    raw = payload.get(CLIENT_GIT_COMMIT_FACTS_KEY)
    if not isinstance(raw, dict):
        return None
    if raw.get("schema") != CLIENT_GIT_COMMIT_FACTS_SCHEMA:
        return None
    if raw.get("is_git_commit") is not True:
        return None
    return raw


def client_list(facts: Mapping[str, object], key: str) -> list[str]:
    """Return a string list from one client-facts key."""
    raw = facts.get(key)
    if not isinstance(raw, list):
        return []
    return [value for value in raw if isinstance(value, str) and value]


__all__ = [
    "client_facts",
    "client_list",
]
