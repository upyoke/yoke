"""One-shot seed: pre-populate path-claim and session-cwd guard event names.

The path-claim and session-cwd guards emit lifecycle events that the
``lint_event_registry`` hook will refuse to write unless the registry
contains an active row for each. This module pre-registers those rows in
one idempotent pass:

- ``PathClaimEditGuardDenied`` (event_type=``path_claim``)
- ``PathClaimBashGuardDenied`` (event_type=``path_claim``)
- ``SessionCwdMismatchDenied`` (event_type=``session_cwd``)
- ``SessionCwdMismatchAllowedReadOnly`` (event_type=``session_cwd``)
- ``SessionCwdBindingFailOpen`` (event_type=``session_cwd``)
- ``SessionCwdBindingHealthCheckFailed`` (event_type=``session_cwd``)

All rows land with ``event_kind=lifecycle``, ``owner_service=cli``,
``status=active``, and a one-line description. Re-running the seed is a
no-op because the underlying ``cmd_registry_add`` is idempotent. This is
a regular event-registry row insert, not a governed migration.

Public surface:

- :data:`SEED_ROWS` — the curated row tuples (introspectable for tests).
- :func:`seed` — idempotent insert pass.
- :func:`main` — CLI entry point (``python3 -m
  yoke_core.domain.event_registry_seed_path_claim_session_cwd``).
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence, Tuple

from yoke_core.domain.events_reporting import cmd_registry_add


# Each tuple is (event_name, event_kind, event_type, owner_service,
# description, severity). Event names are PascalCase per the existing
# event registry convention; descriptions are one-line.
SEED_ROWS: Tuple[Tuple[str, str, str, str, str, str], ...] = (
    (
        "PathClaimEditGuardDenied",
        "lifecycle",
        "path_claim",
        "cli",
        "PreToolUse Edit/Write blocked by path-claim guard for unowned path",
        "WARN",
    ),
    (
        "PathClaimBashGuardDenied",
        "lifecycle",
        "path_claim",
        "cli",
        "PreToolUse Bash blocked by path-claim guard for unowned target path",
        "WARN",
    ),
    (
        "SessionCwdMismatchDenied",
        "lifecycle",
        "session_cwd",
        "cli",
        "PreToolUse blocked because session cwd does not match the bound worktree",
        "WARN",
    ),
    (
        "SessionCwdMismatchAllowedReadOnly",
        "lifecycle",
        "session_cwd",
        "cli",
        "PreToolUse cwd mismatch was allowed because the command matched a read-only / self-orientation signature",
        "INFO",
    ),
    (
        "SessionCwdBindingFailOpen",
        "lifecycle",
        "session_cwd",
        "cli",
        "Session-cwd binding could not be resolved; guard fell open and allowed the call",
        "WARN",
    ),
    (
        "SessionCwdBindingHealthCheckFailed",
        "lifecycle",
        "session_cwd",
        "cli",
        "Session-cwd binding health check detected an inconsistent worktree binding",
        "WARN",
    ),
)


def seed(db_path: Optional[str] = None) -> None:
    """Insert each seed row idempotently via ``cmd_registry_add``.

    Idempotent: re-running the seed leaves existing rows untouched
    because :func:`cmd_registry_add` is keyed on ``event_name``.
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
            "Seed event_registry with the path-claim and session-cwd "
            "guard event names. Idempotent."
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
