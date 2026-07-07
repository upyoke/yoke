"""One-shot seed: pre-populate Yoke function-call dispatcher event names.

The dispatcher (``yoke_function_dispatch.dispatch``) emits four
lifecycle events. The events-registry audit will refuse to write unless
each carries an ``active`` row in ``event_registry``. This module
pre-registers all four in one idempotent pass:

- ``YokeFunctionCalled`` — one per call. Carries function id, version,
  target, payload byte count + checksum, guardrail outcomes, verification
  status, sync status, and handler-supplied event ids. Identity-binder
  findings ride the context on every dispatcher event:
  ``session_override`` (+ the divergent ``ambient_session_id``) marks the
  operator-debug explicit-session path, and ``provenance_unverified``
  marks calls whose bound session has no ``harness_sessions`` row.
- ``DispatcherIdempotencyReplay`` — fired when a prior ``(function,
  request_id)`` is replayed.
- ``DispatcherDownstreamDegraded`` — fired when at least one
  ``FunctionWarning`` lands on the response envelope.
- ``YokeFunctionPermissionDenied`` — fired when dispatcher authz
  refuses a call before handler execution.

All rows land with ``event_kind=lifecycle``, ``event_type=function_call``,
``owner_service=cli``, ``status=active``. Re-running the seed is a no-op
because :func:`yoke_core.domain.events_reporting.cmd_registry_add`
is idempotent.

Public surface:

- :data:`SEED_ROWS` — curated row tuples (introspectable for tests).
- :func:`seed` — idempotent insert pass.
- :func:`seeded_event_names` — names this seed registers.
- :func:`main` — CLI entry point.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence, Tuple

from yoke_core.domain.events_reporting import cmd_registry_add


# Each tuple is (event_name, event_kind, event_type, owner_service,
# description, severity).
SEED_ROWS: Tuple[Tuple[str, str, str, str, str, str], ...] = (
    (
        "YokeFunctionCalled",
        "lifecycle",
        "function_call",
        "cli",
        "Yoke function-call dispatcher invoked a registered handler",
        "INFO",
    ),
    (
        "DispatcherIdempotencyReplay",
        "lifecycle",
        "function_call",
        "cli",
        "Dispatcher replayed a prior result for a repeated (function, request_id)",
        "INFO",
    ),
    (
        "DispatcherDownstreamDegraded",
        "lifecycle",
        "function_call",
        "cli",
        "Dispatcher recorded one or more downstream-degraded warnings on a call",
        "WARN",
    ),
    (
        "YokeFunctionPermissionDenied",
        "lifecycle",
        "function_call",
        "cli",
        "Dispatcher denied a function call before handler execution",
        "WARN",
    ),
)


def seed(db_path: Optional[str] = None) -> None:
    """Insert each seed row idempotently via ``cmd_registry_add``.

    Idempotent: re-running the seed leaves existing rows untouched.
    """
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
            "Seed event_registry with Yoke function-call dispatcher "
            "event names. Idempotent."
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
