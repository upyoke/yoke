"""Bounded allowlist for relay result evidence persisted by the server."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_core.domain import json_helper


def redacted_evidence(value: Mapping[str, Any] | None) -> str:
    return json_helper.dumps_compact(redacted_evidence_document(value))


def merge_redacted_evidence(
    existing: Any,
    incoming: Mapping[str, Any] | None,
) -> str:
    """Merge a relay report without discarding server-authored safe facts."""
    try:
        stored = json_helper.loads_text(str(existing))
    except (TypeError, ValueError):
        stored = {}
    source = stored if isinstance(stored, Mapping) else {}
    merged = redacted_evidence_document(incoming)
    digest = source.get("native_instruction_sha256")
    if isinstance(digest, str) and digest.strip():
        merged["native_instruction_sha256"] = digest
    return redacted_evidence(merged)


__all__ = [
    "merge_redacted_evidence",
    "redacted_evidence",
    "redacted_evidence_document",
]
