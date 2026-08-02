"""Event registry/catalog checks that read this repo's own source tree.

* ``HC-event-callsite-registry-sync`` — every event emitted from a call
  site in this checkout is registered in ``event_registry``.
* ``HC-event-catalog-drift`` — ``docs/event-catalog.md`` in this checkout
  matches the active rows in ``event_registry``.

Both answer a question about the Yoke source tree, so they belong to the
project rather than to every install the engine ships to.
"""

from __future__ import annotations

import os
from typing import List

from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.events_crud import cmd_registry_discover

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


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


__all__ = ["hc_event_callsite_registry_sync", "hc_event_catalog_drift"]

# Slug and display name are the ones this check has always reported under.
from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    ('event-callsite-registry-sync', 'Event call site registry sync', hc_event_callsite_registry_sync),
    ('event-catalog-drift', 'Event catalog drift', hc_event_catalog_drift),
)
