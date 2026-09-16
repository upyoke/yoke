"""Time-bounded targeted debug capture on the existing log stack.

A campaign is process environment, the same control family as
``YOKE_API_LOG_LEVEL``. It never attaches correlation identifiers to
metrics. Consumers call :func:`debug_detail_allowed` before emitting
extra diagnostic payload (for example a full function result).
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from yoke_core.domain.time_parse import parse_timestamp_utc


DEBUG_SCOPE_ENV = "YOKE_API_DEBUG_SCOPE"
DEBUG_UNTIL_ENV = "YOKE_API_DEBUG_UNTIL"
DEBUG_MAX_RECORDS_ENV = "YOKE_API_DEBUG_MAX_RECORDS"

SCOPE_KINDS = ("function", "session", "service", "request")
DEFAULT_MAX_RECORDS = 200
MAX_RECORDS_CAP = 2000

_SCOPE_CONTEXT_KEYS = {
    "function": ("function", "yoke.function"),
    "session": ("session_id", "yoke.session_id"),
    "service": ("service",),
    "request": ("request_id", "yoke.request_id"),
}

_lock = threading.Lock()
_emitted = 0
_identity = ""


@dataclass(frozen=True)
class DebugCampaign:
    """Active capture window: one scope, a hard end time, a record cap."""

    kind: str
    value: str
    until: datetime
    max_records: int

    @property
    def identity(self) -> str:
        return f"{self.kind}:{self.value}:{self.until.isoformat()}:{self.max_records}"


class DebugCaptureFilter(logging.Filter):
    """Drop DEBUG unless a live campaign matches, or process DEBUG is set."""

    def __init__(self, configured_level: int) -> None:
        super().__init__()
        self.configured_level = configured_level

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.INFO:
            return True
        campaign = parse_debug_campaign()
        if campaign is None:
            return record.levelno >= self.configured_level
        return debug_detail_allowed(context_from_record(record))


def parse_debug_campaign(
    env: Optional[Mapping[str, str]] = None,
    *,
    now: Optional[datetime] = None,
) -> Optional[DebugCampaign]:
    """Return the live campaign, or ``None`` when unset, invalid, or expired."""
    source = os.environ if env is None else env
    raw_scope = str(source.get(DEBUG_SCOPE_ENV, "")).strip()
    raw_until = str(source.get(DEBUG_UNTIL_ENV, "")).strip()
    if not raw_scope or not raw_until:
        return None
    kind, sep, value = raw_scope.partition(":")
    kind = kind.strip().lower()
    value = value.strip()
    if not sep or kind not in SCOPE_KINDS or not value:
        return None
    until = parse_timestamp_utc(raw_until)
    if until is None:
        return None
    anchor = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    if until <= anchor.astimezone(timezone.utc):
        return None
    return DebugCampaign(
        kind=kind,
        value=value,
        until=until,
        max_records=_parse_max_records(source.get(DEBUG_MAX_RECORDS_ENV, "")),
    )


def debug_detail_allowed(
    context: Optional[Mapping[str, Any]] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    now: Optional[datetime] = None,
    consume: bool = True,
) -> bool:
    """True when this record is in scope, unexpired, and under the output cap."""
    campaign = parse_debug_campaign(env, now=now)
    if campaign is None or not _matches(campaign, context or {}):
        return False
    global _emitted, _identity
    with _lock:
        if _identity != campaign.identity:
            _identity = campaign.identity
            _emitted = 0
        if _emitted >= campaign.max_records:
            return False
        if consume:
            _emitted += 1
        return True


def debug_records_emitted() -> int:
    with _lock:
        return _emitted


def reset_debug_state() -> None:
    """Test helper: clear the in-process capture counter."""
    global _emitted, _identity
    with _lock:
        _emitted = 0
        _identity = ""


def context_from_record(record: logging.LogRecord) -> dict[str, Any]:
    """Project logging extras (and nested ``context``) into campaign keys."""
    nested = getattr(record, "context", None)
    nested_map = nested if isinstance(nested, Mapping) else {}
    projected: dict[str, Any] = {}
    for keys in _SCOPE_CONTEXT_KEYS.values():
        for key in keys:
            value = getattr(record, key, None)
            if value in (None, ""):
                value = nested_map.get(key)
            if value not in (None, ""):
                projected[key] = value
    return projected


def _matches(campaign: DebugCampaign, context: Mapping[str, Any]) -> bool:
    expected = str(campaign.value)
    for key in _SCOPE_CONTEXT_KEYS[campaign.kind]:
        value = context.get(key)
        if value not in (None, "") and str(value) == expected:
            return True
    return False


def _parse_max_records(raw: object) -> int:
    text = str(raw or "").strip()
    if not text:
        return DEFAULT_MAX_RECORDS
    try:
        parsed = int(text)
    except (TypeError, ValueError):
        return DEFAULT_MAX_RECORDS
    return max(1, min(parsed, MAX_RECORDS_CAP))


__all__ = [
    "DEBUG_MAX_RECORDS_ENV",
    "DEBUG_SCOPE_ENV",
    "DEBUG_UNTIL_ENV",
    "DEFAULT_MAX_RECORDS",
    "DebugCampaign",
    "DebugCaptureFilter",
    "MAX_RECORDS_CAP",
    "SCOPE_KINDS",
    "context_from_record",
    "debug_detail_allowed",
    "debug_records_emitted",
    "parse_debug_campaign",
    "reset_debug_state",
]
