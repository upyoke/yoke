"""Bounded evidence shared by relay clients and the control plane."""

from __future__ import annotations

from typing import Any, Mapping


_TEXT_FIELDS = frozenset({"adapter_revision", "result_code", "surface"})
_INTEGER_FIELDS = frozenset({"duration_ms", "exit_code"})
_MAX_TEXT_LENGTH = 128


def redacted_evidence_document(
    value: Mapping[str, Any] | None,
) -> dict[str, str | int]:
    """Keep bounded non-secret facts and omit every unknown field."""
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


__all__ = ["redacted_evidence_document"]
