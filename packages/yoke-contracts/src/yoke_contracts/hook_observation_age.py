"""How long ago, at hand-off to its authority, a hook was observed.

A hook whose evaluation outlives its client (a resident timeout) still
finishes later, and the authority must not mistake that late result for
new activity: an ended session would otherwise come back to life. The hook
client's start is a system-wide monotonic instant on the same machine as
the evaluator, so the evaluator stamps the hook's age into the payload
just before handing it to the authority. The authority reconstructs the
observation instant on its own clock (``now - age``), so client clock skew
never enters the comparison.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

from yoke_contracts.hook_evaluator_protocol import EVALUATOR_PAYLOAD_KEY

HOOK_AGE_FIELD = "hook_age_ms"

#: A hook older than this is not a measurement anyone should trust.
MAX_HOOK_AGE_MS = 24 * 60 * 60 * 1000


def stamp_hook_age(stdin_data: str, started_monotonic: float | None) -> str:
    """Record the hook's age now; unchanged when the start is unknown."""
    if started_monotonic is None:
        return stdin_data
    try:
        payload = json.loads(stdin_data) if stdin_data else {}
    except (TypeError, ValueError):
        return stdin_data
    if not isinstance(payload, dict):
        return stdin_data
    age = max(0, int((time.monotonic() - started_monotonic) * 1000))
    metadata = payload.get(EVALUATOR_PAYLOAD_KEY)
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    metadata[HOOK_AGE_FIELD] = min(age, MAX_HOOK_AGE_MS)
    payload[EVALUATOR_PAYLOAD_KEY] = metadata
    return json.dumps(payload, separators=(",", ":"))


def hook_age_ms(payload: Any) -> int | None:
    """The stamped age, or ``None`` when absent or malformed."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload) if payload else {}
        except (TypeError, ValueError):
            return None
    metadata = payload.get(EVALUATOR_PAYLOAD_KEY) if isinstance(payload, dict) else None
    value = metadata.get(HOOK_AGE_FIELD) if isinstance(metadata, dict) else None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= MAX_HOOK_AGE_MS else None


def observed_at(payload: Any, now: datetime) -> datetime | None:
    """When the hook was observed, on the authority's clock."""
    age = hook_age_ms(payload)
    return None if age is None else now - timedelta(milliseconds=age)


__all__ = [
    "HOOK_AGE_FIELD",
    "MAX_HOOK_AGE_MS",
    "hook_age_ms",
    "observed_at",
    "stamp_hook_age",
]
