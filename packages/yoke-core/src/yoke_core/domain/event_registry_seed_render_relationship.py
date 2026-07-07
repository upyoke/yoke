"""One-shot seed: pre-register the render-relationship event name.

The path-context writers in :mod:`yoke_core.domain.path_context`
require a recorded ``events.event_id`` for every row they author
(provenance is mandatory; see ``put_context_value``). The renderer
bridge in :mod:`yoke_core.domain.agents_render_path_context` emits
one batch-level ``RenderRelationshipRecorded`` event per call so the
``FAMILY_RENDER_TARGET`` / ``FAMILY_RENDER_SOURCE`` rows it writes
share a single provenance row.

This module is the single writer that pre-registers the event name in
``event_registry`` so the ``lint_event_registry`` hook accepts the
emission. Re-running is a no-op because :func:`cmd_registry_add` is
idempotent.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence, Tuple

from yoke_core.domain.events_reporting import cmd_registry_add


EVENT_NAME_RENDER_RELATIONSHIP_RECORDED = "RenderRelationshipRecorded"

SEED_ROWS: Tuple[Tuple[str, str, str, str, str, str], ...] = (
    (
        EVENT_NAME_RENDER_RELATIONSHIP_RECORDED,
        "lifecycle",
        "path_context",
        "cli",
        "Batch-level provenance event for FAMILY_RENDER_TARGET/SOURCE rows",
        "INFO",
    ),
)


def seed(db_path: Optional[str] = None) -> None:
    """Insert the seed row idempotently via ``cmd_registry_add``."""
    for row in SEED_ROWS:
        name, kind, event_type, service, description, severity = row
        cmd_registry_add(
            db_path=db_path,
            name=name,
            kind=kind,
            event_type=event_type,
            service=service,
            description=description,
            severity=severity,
        )


def seeded_event_names() -> Sequence[str]:
    """Return the event-name list this seed registers (test introspection)."""
    return tuple(row[0] for row in SEED_ROWS)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Seed event_registry with the render-relationship event name. "
            "Idempotent."
        )
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Yoke DB connection override (defaults to configured authority).",
    )
    args = parser.parse_args(argv)
    seed(db_path=args.db)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
