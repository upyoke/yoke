"""Endpoint-fact delta between two QA execution-target snapshots.

Identity (environment row, subject) is a different axis. Two snapshots can
name the same environment and still send a case to a different host. This
module reports which endpoint facts moved, and whether any resolved host
authority changed, so a rebind can stay honest about what it cannot prove.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if "://" in text else f"https://{text}"


def endpoint_authority(value: Any) -> str:
    """Return ``host[:port]`` after defaulting a missing scheme to https."""
    text = _as_url(value)
    if not text:
        return ""
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return parsed.netloc.lower()


def _flatten(endpoints: Mapping[str, Any]) -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in endpoints.items():
        if key == "capability_endpoints" and isinstance(value, Mapping):
            for inner, inner_val in value.items():
                if not isinstance(inner_val, Mapping):
                    flat[f"capability_endpoints.{inner}"] = str(inner_val or "")
            continue
        if isinstance(value, Mapping):
            continue
        flat[str(key)] = str(value or "")
    return flat


def _kind(old: str, new: str) -> str:
    if old == new:
        return "unchanged"
    if not old:
        return "added"
    if not new:
        return "removed"
    old_auth, new_auth = endpoint_authority(old), endpoint_authority(new)
    if old_auth and new_auth and old_auth != new_auth:
        return "authority"
    if old_auth and new_auth:
        old_scheme = urlsplit(_as_url(old)).scheme
        new_scheme = urlsplit(_as_url(new)).scheme
        return "scheme" if old_scheme != new_scheme else "url"
    return "scalar"


def endpoint_delta(
    stored: Mapping[str, Any] | None, live: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Diff ``endpoints`` (including capability URLs) between two snapshots."""
    old_map = _flatten(_mapping(_mapping(stored).get("endpoints")))
    new_map = _flatten(_mapping(_mapping(live).get("endpoints")))
    changed: list[dict[str, str]] = []
    authority_changed: list[str] = []
    for key in sorted(set(old_map) | set(new_map)):
        old, new = old_map.get(key, ""), new_map.get(key, "")
        kind = _kind(old, new)
        if kind == "unchanged":
            continue
        changed.append({"key": key, "from": old, "to": new, "kind": kind})
        if kind == "authority":
            authority_changed.append(key)
    return {"changed": changed, "authority_changed": authority_changed}


def summarize_endpoint_delta(delta: Mapping[str, Any]) -> str:
    """One-line teaching of which facts moved."""
    parts = [
        f"{row['key']} {row['from']!r} -> {row['to']!r} ({row['kind']})"
        for row in (delta.get("changed") or [])
        if isinstance(row, Mapping)
    ]
    return "; ".join(parts) if parts else "no endpoint facts moved"


__all__ = [
    "endpoint_authority",
    "endpoint_delta",
    "summarize_endpoint_delta",
]
