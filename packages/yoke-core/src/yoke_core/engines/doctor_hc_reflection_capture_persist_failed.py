"""HC-reflection-capture-persist-failed.

Surfaces silent reflection-capture persist drops in the last 24h.

``persist_entries`` (``yoke_core.domain.reflection_capture``) wraps every
``cmd_insert_entry`` call in a broad ``except Exception`` and records the
failure on the ``CaptureResult.errors`` list. When that list is non-empty,
the persist path also emits a ``ReflectionCapturePersistFailed`` event
carrying the failing entry's ``agent``, ``category``, ``body_excerpt`` (first
200 chars), and ``exception_type`` so operators can see exactly which
reflections were silently dropped.

This health check queries those events in the last 24h and surfaces them as
WARN with the dropped-entry counts. Self-skips cleanly on minimal-schema
fixtures (missing ``events`` table) so it degrades to PASS in
test/empty-history contexts instead of FAIL.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-reflection-capture-persist-failed"
_HC_DESC = (
    "ReflectionCapturePersistFailed events in the last 24h "
    "(silently dropped subagent reflections needing operator attention)"
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _events_table_present(conn: Any) -> bool:
    try:
        return _table_exists(conn, "events")
    except Exception:
        return False


def _parse_payload(payload_text: Any) -> dict | None:
    if not payload_text:
        return None
    try:
        if isinstance(payload_text, (bytes, bytearray)):
            payload_text = payload_text.decode("utf-8", errors="ignore")
        if isinstance(payload_text, str):
            parsed = json.loads(payload_text)
        elif isinstance(payload_text, dict):
            parsed = payload_text
        else:
            return None
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _cutoff_24h() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _persist_failed_entries_24h(conn: Any) -> list[dict]:
    try:
        p = _p(conn)
        rows = conn.execute(
            "SELECT payload, created_at FROM events "
            "WHERE event_name='ReflectionCapturePersistFailed' "
            f"AND created_at >= {p} "
            "ORDER BY created_at DESC",
            (_cutoff_24h(),),
        ).fetchall()
    except db_backend.database_error_types(conn):
        return []
    out: list[dict] = []
    for row in rows:
        parsed = _parse_payload(row[0])
        if not parsed:
            continue
        out.append({
            "created_at": row[1],
            "agent": parsed.get("agent"),
            "category": parsed.get("category"),
            "body_excerpt": parsed.get("body_excerpt"),
            "exception_type": parsed.get("exception_type"),
        })
    return out


def hc_reflection_capture_persist_failed(
    conn: Any, args: DoctorArgs, rec: RecordCollector,
) -> None:
    if not _events_table_present(conn):
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "events table not present (fixture/minimal-schema context); skipping",
        )
        return

    entries = _persist_failed_entries_24h(conn)
    if not entries:
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "no ReflectionCapturePersistFailed events in the last 24h",
        )
        return

    by_category: dict[str, int] = {}
    by_exception: dict[str, int] = {}
    for entry in entries:
        cat = entry.get("category") or "(unknown)"
        exc = entry.get("exception_type") or "(unknown)"
        by_category[cat] = by_category.get(cat, 0) + 1
        by_exception[exc] = by_exception.get(exc, 0) + 1

    detail_lines = [
        f"{len(entries)} ReflectionCapturePersistFailed event(s) "
        "in the last 24h. Each names one parsed reflection that did NOT "
        "land in ouroboros_entries:",
    ]
    for entry in entries[:10]:
        excerpt = (entry.get("body_excerpt") or "")[:120]
        detail_lines.append(
            f"- {entry['created_at']} agent={entry['agent']} "
            f"category={entry['category']} "
            f"exception={entry['exception_type']} "
            f"excerpt={excerpt!r}",
        )
    if len(entries) > 10:
        detail_lines.append(f"... ({len(entries) - 10} more)")
    detail_lines.append(
        "By category: "
        + ", ".join(f"{k}={v}" for k, v in sorted(by_category.items())),
    )
    detail_lines.append(
        "By exception: "
        + ", ".join(f"{k}={v}" for k, v in sorted(by_exception.items())),
    )
    detail_lines.append(
        "Remediation: review "
        "python3 -m yoke_core.cli.db_router events list "
        "--event-name ReflectionCapturePersistFailed --since '24 hours ago' "
        "and inspect the root cause; the most common class is a schema "
        "drift on ouroboros_entries or a transient DB lock.",
    )
    rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(detail_lines))


__all__ = ["hc_reflection_capture_persist_failed"]
