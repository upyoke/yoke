"""Event registry population and event-catalog.md rendering.

The retired ``populate-registry.sh`` shell wrapper now resolves directly to
this Python owner.

This module replaces the 494-line shell script that historically mixed four
responsibilities:

1. **Discovery** — scan the codebase for legacy event-emitter ``--name`` call
   sites (delegated to :func:`events_crud.cmd_registry_discover`).
2. **Metadata inference** — guess ``owner_service``, ``event_kind``,
   ``event_type``, and ``severity_default`` from file paths and event names
   for newly discovered events.
3. **Corrective metadata updates** — override auto-inferred (and therefore
   occasionally wrong) metadata for curated events so the
   ``event-catalog.md`` catalog reflects authoritative values.
4. **Catalog rendering** — emit ``docs/event-catalog.md`` as a
   human-readable markdown table.

The data tuples that drive the curated, corrective, deprecate, retire,
and authoritative-metadata layers live in sibling modules:

- :mod:`yoke_core.domain.populate_registry_data_curated`
- :mod:`yoke_core.domain.populate_registry_data_authoritative`

The metadata-application helpers live in
:mod:`yoke_core.domain.populate_registry_apply`. The catalog renderer
and repo-root resolver live in
:mod:`yoke_core.domain.populate_registry_render`. All of those names
remain importable from this module via re-export so existing callers keep
working.

The idempotency contract is preserved: running the populator twice is a
no-op (``0 newly registered``).  Public entry point:

    python3 -m yoke_core.domain.populate_registry

Exit codes: 0 success, 1 unexpected error.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from yoke_core.domain import events_crud
from yoke_core.domain.populate_registry_apply import (
    _apply_corrective_updates,
    _cleanup_test_sourced_entries,
    _deprecate_retired_events,
    _ensure_authoritative_metadata,
    _ensure_registry_entry,
    _register_curated_events,
    _retire_events,
    _set_owner_service,
)
from yoke_core.domain.populate_registry_data_authoritative import (
    AUTHORITATIVE_METADATA,
    DEPRECATE_LIST,
    RETIRE_LIST,
)
from yoke_core.domain.populate_registry_data_curated import (
    CORRECTIVE_UPDATES,
    CURATED_EVENTS,
    SEVERITY_ONLY_UPDATES,
)
from yoke_core.domain.populate_registry_render import (
    _render_catalog,
    _resolve_repo_root,
)


__all__ = [
    # Inference helpers (defined here)
    "infer_owner_service",
    "infer_event_kind",
    "infer_event_type",
    "infer_severity",
    # Data tuples (re-exported from data siblings)
    "CURATED_EVENTS",
    "CORRECTIVE_UPDATES",
    "SEVERITY_ONLY_UPDATES",
    "DEPRECATE_LIST",
    "RETIRE_LIST",
    "AUTHORITATIVE_METADATA",
    # Apply helpers (re-exported)
    "_ensure_registry_entry",
    "_register_curated_events",
    "_apply_corrective_updates",
    "_set_owner_service",
    "_ensure_authoritative_metadata",
    "_deprecate_retired_events",
    "_retire_events",
    "_cleanup_test_sourced_entries",
    # Catalog rendering (re-exported)
    "_resolve_repo_root",
    "_render_catalog",
    # Public entry points
    "populate",
    "populate_and_render",
    "main",
]


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------


def infer_owner_service(file_path: str) -> str:
    """Return the basename of *file_path* with a trailing ``.sh`` stripped."""
    base = os.path.basename(file_path)
    if base.endswith(".sh"):
        base = base[:-3]
    return base


def infer_event_kind(event_name: str) -> str:
    """Guess ``event_kind`` from the event name."""
    if event_name.endswith("ToolCallDenied"):
        return "audit"
    if "ToolCall" in event_name:
        return "system"
    if "Session" in event_name:
        return "system"
    if "Anomaly" in event_name:
        return "system"
    if "Shepherd" in event_name:
        return "audit"
    if "Conduct" in event_name:
        return "system"
    if "Deployment" in event_name:
        return "system"
    if "Test" in event_name:
        return "system"
    if "Health" in event_name:
        return "system"
    if "Pattern" in event_name:
        return "system"
    if "ItemStatus" in event_name:
        return "lifecycle"
    if "TaskStatus" in event_name:
        return "lifecycle"
    if event_name.endswith("StatusChanged"):
        return "lifecycle"
    return "system"


_EVENT_TYPE_SUFFIXES: Tuple[Tuple[str, str], ...] = (
    ("Started", "Started"),
    ("Completed", "Completed"),
    ("Failed", "Failed"),
    ("Passed", "Passed"),
    ("Changed", "Changed"),
    ("Dispatched", "Dispatched"),
    ("Detected", "Detected"),
    ("Promoted", "Promoted"),
    ("Stopped", "Stopped"),
    ("Ended", "Ended"),
    ("Created", "Created"),
    ("Updated", "Updated"),
    ("Deleted", "Deleted"),
)


def infer_event_type(event_name: str) -> str:
    """Guess ``event_type`` from the event name suffix."""
    for suffix, label in _EVENT_TYPE_SUFFIXES:
        if event_name.endswith(suffix):
            return label
    return "Unknown"


def infer_severity(event_name: str) -> str:
    """Guess ``severity_default`` from the event name."""
    if event_name.endswith("Failed"):
        return "WARN"
    if "Anomaly" in event_name:
        return "WARN"
    return "INFO"


# ---------------------------------------------------------------------------
# Discovery + registration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DiscoverySummary:
    total_discovered: int
    newly_registered: int
    existing_discovered: int


def _parse_discovery_output(raw: str) -> List[Tuple[str, str]]:
    """Return deduped ``(event_name, file_path)`` pairs from discover output."""
    seen: set[str] = set()
    out: List[Tuple[str, str]] = []
    for line in raw.splitlines():
        if "|" not in line:
            continue
        name, _, path = line.partition("|")
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append((name, path.strip()))
    return out


def _registry_get_silent(db_path: Optional[str], name: str) -> bool:
    """Return True if *name* already exists in the registry."""
    try:
        events_crud.cmd_registry_get(db_path=db_path, name=name)
    except LookupError:
        return False
    except Exception:
        return False
    return True


def _register_discovered(
    db_path: Optional[str], entries: Sequence[Tuple[str, str]]
) -> _DiscoverySummary:
    """Register each *(name, path)* entry; count new vs existing."""
    newly = 0
    existing = 0
    for name, path in entries:
        owner = infer_owner_service(path)
        kind = infer_event_kind(name)
        event_type = infer_event_type(name)
        severity = infer_severity(name)
        desc = f"Auto-discovered from {path}"
        was_registered = _registry_get_silent(db_path, name)
        events_crud.cmd_registry_add(
            db_path=db_path,
            name=name,
            kind=kind,
            event_type=event_type,
            service=owner,
            description=desc,
            severity=severity,
        )
        if was_registered:
            existing += 1
        else:
            newly += 1
    return _DiscoverySummary(
        total_discovered=len(entries),
        newly_registered=newly,
        existing_discovered=existing,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def populate(
    db_path: Optional[str] = None,
    repo_root: Optional[str] = None,
) -> str:
    """DB-population pipeline without the catalog render; returns the
    summary line. Environment bootstrap consumes this form — a fresh
    env DB needs the registry rows, not a docs write."""
    resolved_root = _resolve_repo_root(repo_root)

    # Ensure the event_registry table exists (idempotent).
    events_crud.cmd_init(db_path=db_path)

    count_before = events_crud.cmd_registry_count(db_path=db_path, status="all")

    # Discovery: events_crud already handles repo_root inference.
    discover_raw = events_crud.cmd_registry_discover(repo_root=str(resolved_root))
    discovered = _parse_discovery_output(discover_raw)
    summary = _register_discovered(db_path, discovered)

    # Curated + corrective + native + authoritative metadata layers.
    _register_curated_events(db_path)
    _apply_corrective_updates(db_path)
    _ensure_authoritative_metadata(db_path)

    # Deprecate / retire.
    _deprecate_retired_events(db_path)
    _retire_events(db_path)
    _cleanup_test_sourced_entries(db_path, discovered)

    # Counts after the full pipeline.
    count_after = events_crud.cmd_registry_count(db_path=db_path, status="all")
    curated_delta = count_after - count_before - summary.newly_registered
    if curated_delta < 0:
        curated_delta = 0
    deprecated = events_crud.cmd_registry_count(db_path=db_path, status="deprecated")

    return (
        f"{summary.total_discovered} total discovered, "
        f"{summary.newly_registered} newly registered, "
        f"{summary.existing_discovered} already registered, "
        f"{curated_delta} curated ensured, "
        f"{deprecated} deprecated"
    )


def populate_and_render(db_path=None, repo_root=None) -> str:
    """Populate the registry, then render ``docs/event-catalog.md``."""
    summary = populate(db_path, repo_root)
    _render_catalog(db_path, _resolve_repo_root(repo_root))
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="populate-registry",
        description="Populate event_registry and render event-catalog.md",
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        default=None,
        help="Yoke DB connection override (defaults to configured authority).",
    )
    parser.add_argument(
        "--repo-root",
        dest="repo_root",
        default=None,
        help="Explicit repo root (defaults to YOKE_REPO_ROOT / YOKE_ROOT / git rev-parse).",
    )
    args = parser.parse_args(argv)

    try:
        summary = populate_and_render(
            db_path=args.db_path,
            repo_root=args.repo_root,
        )
    except Exception as exc:  # pragma: no cover — defensive top-level
        print(f"populate-registry: {exc}", file=sys.stderr)
        return 1

    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
