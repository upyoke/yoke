"""Disposable diagnostics: a bounded server event for each collector refusal kind.

The anonymous collector answers every refusal to its caller; this module also
leaves a server-side record an operator can read with
``yoke events query --event-name FrontendCollectorRefused``. The record is
telemetry only: nothing operational reads it, and a failed write never
changes the refusal the caller receives.

An attacker controls how often refusals happen, so the record is rate-limited
by construction. The event id is derived from (reason, status, route, minute),
so the event sink's ``ON CONFLICT(event_id) DO NOTHING`` keeps at most one row
per refusal kind per minute across every process, and an in-process memo skips
repeat writes before they reach the database. Reasons, statuses and routes are
server-authored, so the key space is finite. No request body, cookie, key or
client address is recorded; the caller-supplied Origin is truncated.
"""

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from yoke_core.domain import db_backend
from yoke_core.domain.events_writes import cmd_insert

REFUSAL_EVENT = "FrontendCollectorRefused"
REFUSAL_WINDOW_SECONDS = 60
ORIGIN_MAX_CHARS = 200

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_recorded = set()


def _authority():
    """Hash the bound database so one process serving two universes keeps both."""
    try:
        return hashlib.sha256(db_backend.resolve_pg_dsn().encode()).hexdigest()
    except Exception:
        return ""


def _first_in_window(key, window):
    with _lock:
        if key in _recorded:
            return False
        _recorded.difference_update({k for k in _recorded if k[0] < window})
        _recorded.add(key)
        return True


def record_refusal(*, reason, status, route, origin, host, now=None):
    """Record one refusal kind per minute; never raise into the refusing route."""
    now = int(time.time() if now is None else now)
    window = now - now % REFUSAL_WINDOW_SECONDS
    if not _first_in_window((window, _authority(), reason, status, route), window):
        return False
    window_start = datetime.fromtimestamp(window, timezone.utc)
    event_id = str(
        uuid5(NAMESPACE_URL, f"yoke:{REFUSAL_EVENT}:{reason}:{status}:{route}:{window}")
    )
    detail = {
        "reason": reason,
        "status": status,
        "route": route,
        "origin": (origin or "")[:ORIGIN_MAX_CHARS],
        "host": host,
        "window_start": window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_seconds": REFUSAL_WINDOW_SECONDS,
    }
    envelope = {
        "event_id": event_id,
        "event_name": REFUSAL_EVENT,
        "event_kind": "system",
        "event_type": "collector_refusal",
        "source_type": "backend",
        "service": "frontend-collector",
        "severity": "WARN",
        "event_outcome": reason,
        "context": {"detail": detail},
    }
    try:
        return cmd_insert(
            event_id=event_id,
            source_type="backend",
            session_id="system:frontend-collector",
            event_kind="system",
            event_type="collector_refusal",
            event_name=REFUSAL_EVENT,
            severity="WARN",
            event_outcome=reason,
            service="frontend-collector",
            envelope=json.dumps(envelope, separators=(",", ":")),
        )
    except Exception:
        # Telemetry is disposable: the caller still receives its named refusal.
        _log.warning(
            "collector_refusal_record_failed: %s %s on %s was refused but not "
            "recorded; restore the events table to see refusals",
            status,
            reason,
            route,
            exc_info=True,
        )
        return False
