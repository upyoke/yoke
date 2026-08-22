"""Bounded allowlist for relay result evidence persisted by the server."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import json_helper


_TEXT_FIELDS = frozenset({"adapter_revision", "result_code", "surface"})
_INTEGER_FIELDS = frozenset({"duration_ms", "exit_code"})
_MAX_TEXT_LENGTH = 128


def redacted_evidence_document(
    value: Mapping[str, Any] | None,
) -> dict[str, str | int]:
    """Keep only non-secret result facts; silently omit every other key."""
    source = value if isinstance(value, Mapping) else {}
    clean: dict[str, str | int] = {}
    for key in sorted(_TEXT_FIELDS):
        item = source.get(key)
        if isinstance(item, str) and item.strip():
            clean[key] = item.strip()[:_MAX_TEXT_LENGTH]
    for key in sorted(_INTEGER_FIELDS):
        item = source.get(key)
        if isinstance(item, int) and not isinstance(item, bool):
            clean[key] = item
    return clean


def redacted_evidence(value: Mapping[str, Any] | None) -> str:
    return json_helper.dumps_compact(redacted_evidence_document(value))


__all__ = ["redacted_evidence", "redacted_evidence_document"]
