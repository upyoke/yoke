"""Event catalog drift and callsite registry health checks.

Extracted from doctor_hc_db.py: synthetic event contamination,
event callsite registry sync, and event catalog drift detection.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from yoke_core.domain.db_helpers import connect, query_rows, query_scalar
from yoke_core.domain.events_crud import cmd_registry_discover

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


# ---------------------------------------------------------------------------
# Synthetic event contamination check
# ---------------------------------------------------------------------------

SYNTHETIC_SENTINEL_SESSIONS = (
    "unknown",
    "migration-zero-legacy",
    "status-events-backfill",
)


def hc_synthetic_event_contamination(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """HC-synthetic-event-contamination: Synthetic rows in the canonical ledger."""
    if not _base._table_exists(conn, "events"):
        rec.record(
            "HC-synthetic-event-contamination",
            "Synthetic event contamination",
            "PASS",
            "events table not present, skipping",
        )
        return

    # Contamination patterns: test-derived session IDs that escape the
    # production-session shape.  Both prefix filters and the ``dup`` fixture
    # are covered here — the stable machine-readable ``synthetic_smoke`` tag
    # from ``anomaly_flags`` is ALSO counted as intentional smoke lineage
    # (not contamination) so doctor never nags about documented exceptions.
    total_row = query_scalar(conn, "SELECT COUNT(*) FROM events")
    total = int(total_row) if total_row else 0
    if total == 0:
        rec.record(
            "HC-synthetic-event-contamination",
            "Synthetic event contamination",
            "PASS",
            "events table empty",
        )
        return

    # deliberate case-sensitive match against internal
    # session_id prefixes and anomaly_flag tokens
    contamination_sql = (
        "SELECT COUNT(*) FROM events "
        "WHERE (session_id LIKE 'test-%%' "
        "   OR session_id LIKE 'sess-%%' "
        "   OR session_id = 'dup') "
        "AND (anomaly_flags IS NULL OR anomaly_flags NOT LIKE '%%synthetic_smoke%%')"
    )
    contaminated_row = query_scalar(conn, contamination_sql)
    contaminated = int(contaminated_row) if contaminated_row else 0

    # Intentional smoke rows — tagged with ``synthetic_smoke`` so they are
    # retained but excluded from contamination counts.
    smoke_row = query_scalar(
        conn,
        # deliberate case-sensitive match against internal anomaly_flag token
        "SELECT COUNT(*) FROM events WHERE anomaly_flags LIKE '%%synthetic_smoke%%'",
    )
    smoke = int(smoke_row) if smoke_row else 0

    # Sentinel / backfill lineage is legitimate historical data.  It is
    # reported separately so the operator can tell "real history" apart
    # from "leaked synthetic telemetry".
    placeholders = ",".join(["%s"] * len(SYNTHETIC_SENTINEL_SESSIONS))
    sentinel_row = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM events WHERE session_id IN ({placeholders})",
        SYNTHETIC_SENTINEL_SESSIONS,
    )
    sentinel = int(sentinel_row) if sentinel_row else 0

    if contaminated == 0:
        detail_parts = [
            f"canonical ledger is clean (0 synthetic rows / {total} total)",
            f"intentional smoke rows (anomaly_flags~'synthetic_smoke'): {smoke}",
            f"historical sentinel/backfill rows: {sentinel}",
        ]
        rec.record(
            "HC-synthetic-event-contamination",
            "Synthetic event contamination",
            "PASS",
            " | ".join(detail_parts),
        )
        return

    # Break down contamination by event_name so the operator can see which
    # emission paths are still leaking.
    top_offenders = query_rows(
        conn,
        # deliberate case-sensitive match against internal
        # session_id prefixes and anomaly_flag tokens
        "SELECT event_name, COUNT(*) AS cnt FROM events "
        "WHERE (session_id LIKE 'test-%%' "
        "   OR session_id LIKE 'sess-%%' "
        "   OR session_id = 'dup') "
        "AND (anomaly_flags IS NULL OR anomaly_flags NOT LIKE '%%synthetic_smoke%%') "
        "GROUP BY event_name ORDER BY cnt DESC LIMIT 10",
    )

    pct = (contaminated / total) * 100.0 if total else 0.0
    lines = [
        f"{contaminated} synthetic rows leaked into canonical ledger "
        f"({pct:.2f}% of {total} total).",
        f"Intentional smoke rows (tagged synthetic_smoke): {smoke}",
        f"Legitimate sentinel/backfill rows (not counted): {sentinel}",
        "Top offending event_names:",
    ]
    for row in top_offenders:
        lines.append(f"- {row['event_name']}: {row['cnt']}")
    lines.append(
        "Cleanup: see docs/event-contract.md section 6 "
        "'Synthetic-Row Cleanup Guidance' before deleting rows — the "
        "sentinel session IDs above are legitimate history."
    )

    rec.record(
        "HC-synthetic-event-contamination",
        "Synthetic event contamination",
        "WARN",
        "\n".join(lines),
    )



def hc_event_callsite_registry_sync(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-event-callsite-registry-sync: Event call site registry sync."""
    if not _base._table_exists(conn, "event_registry"):
        rec.record("HC-event-callsite-registry-sync", "Event call site registry sync", "PASS",
                    "event_registry table not present, skipping")
        return

    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-event-callsite-registry-sync", "Event call site registry sync", "PASS", "")
        return

    try:
        discovered = cmd_registry_discover(repo_root)
    except Exception:
        discovered = ""
    if not discovered.strip():
        rec.record("HC-event-callsite-registry-sync", "Event call site registry sync", "PASS", "")
        return

    # Check each discovered event against registry
    unregistered: List[str] = []
    seen: set = set()
    for line in discovered.strip().splitlines():
        parts = line.split("|")
        ev_name = parts[0].strip() if parts else ""
        if not ev_name or ev_name in seen:
            continue
        seen.add(ev_name)
        exists = query_scalar(
            conn, "SELECT COUNT(*) FROM event_registry WHERE event_name=%s", (ev_name,)
        )
        if not exists or int(exists) == 0:
            unregistered.append(f"- {ev_name}")

    if unregistered:
        rec.record("HC-event-callsite-registry-sync", "Event call site registry sync", "WARN",
                    "Unregistered call site events:\n" + "\n".join(unregistered))
    else:
        rec.record("HC-event-callsite-registry-sync", "Event call site registry sync", "PASS", "")



def hc_event_catalog_drift(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-event-catalog-drift: Event catalog matches registry."""
    if not _base._table_exists(conn, "event_registry"):
        rec.record("HC-event-catalog-drift", "Event catalog drift", "PASS",
                    "event_registry table not present, skipping")
        return

    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-event-catalog-drift", "Event catalog drift", "PASS",
                    "Cannot resolve repo root, skipping")
        return

    catalog_path = os.path.join(repo_root, "docs", "event-catalog.md")
    if not os.path.isfile(catalog_path):
        rec.record("HC-event-catalog-drift", "Event catalog drift", "WARN",
                    f"event-catalog.md not found at {catalog_path}. "
                    "Run: python3 -m yoke_core.domain.populate_registry")
        return

    # Get all active registry event names
    rows = query_rows(conn, "SELECT event_name FROM event_registry WHERE status='active' ORDER BY event_name")
    registry_names = {r["event_name"] for r in rows}

    # Parse event names from the catalog markdown table
    catalog_names: set = set()
    try:
        with open(catalog_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("|") or line.startswith("| Event Name") or line.startswith("|---"):
                    continue
                cols = [c.strip() for c in line.split("|")]
                if len(cols) >= 3:
                    name = cols[1]
                    # Only count active entries in the catalog
                    status_col = cols[-2] if len(cols) >= 8 else ""
                    if name and status_col == "active":
                        catalog_names.add(name)
    except OSError:
        rec.record("HC-event-catalog-drift", "Event catalog drift", "WARN",
                    f"Cannot read {catalog_path}")
        return

    missing_from_catalog = registry_names - catalog_names
    extra_in_catalog = catalog_names - registry_names

    issues: List[str] = []
    if missing_from_catalog:
        issues.append("Active registry events missing from catalog:")
        for n in sorted(missing_from_catalog)[:10]:
            issues.append(f"- {n}")
        if len(missing_from_catalog) > 10:
            issues.append(f"  ... and {len(missing_from_catalog) - 10} more")
    if extra_in_catalog:
        issues.append("Catalog lists events not active in registry:")
        for n in sorted(extra_in_catalog)[:10]:
            issues.append(f"- {n}")
        if len(extra_in_catalog) > 10:
            issues.append(f"  ... and {len(extra_in_catalog) - 10} more")

    if issues:
        issues.append("Regenerate: python3 -m yoke_core.domain.populate_registry")
        rec.record("HC-event-catalog-drift", "Event catalog drift", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-event-catalog-drift", "Event catalog drift", "PASS",
                    f"{len(registry_names)} active events in sync between registry and catalog")
