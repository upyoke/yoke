"""Read stored evidence documents the same way wherever a report needs one.

Evidence is written as JSON by relays on several transports and read back by
detectors that must not care whether their driver handed them a mapping or the
text of one.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


def evidence_document(raw: Any) -> dict[str, Any]:
    """Read one stored evidence document, tolerating text or an absent one."""
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, (str, bytes)):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def evidence_text(raw: Any, key: str) -> str:
    value = evidence_document(raw).get(key)
    return value.strip() if isinstance(value, str) else ""


def evidence_int(raw: Any, key: str) -> int | None:
    value = evidence_document(raw).get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = [
    "evidence_document",
    "evidence_int",
    "evidence_text",
]
