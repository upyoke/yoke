"""Bounded allowlist for relay result evidence persisted by the server."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_core.domain import json_helper


def redacted_evidence(value: Mapping[str, Any] | None) -> str:
    return json_helper.dumps_compact(redacted_evidence_document(value))


__all__ = ["redacted_evidence", "redacted_evidence_document"]
