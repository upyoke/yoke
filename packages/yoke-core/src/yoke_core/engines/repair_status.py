"""Emergency status repair front door.

Owns argument parsing, ID normalization, public repair-flow re-exports, and
repair dispatch. Invoked via ``python3 -m yoke_core.engines.repair_status``.

Usage::

    python3 -m yoke_core.engines.repair_status <YOK-N> <new-status> [--reason R]
    python3 -m yoke_core.engines.repair_status --task <epic-id> <task-num> <new-status> [--reason R]
    python3 -m yoke_core.engines.repair_status --dry-run <YOK-N> <new-status>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


USAGE = (
    "  python3 -m yoke_core.engines.repair_status <YOK-N> <new-status> [--reason <reason>]\n"
    "  python3 -m yoke_core.engines.repair_status --task <epic-id> <task-num> <new-status> [--reason <reason>]\n"
    "  python3 -m yoke_core.engines.repair_status --dry-run <YOK-N> <new-status>"
)


class UsageError(Exception):
    """Raised when the operator passes invalid CLI arguments."""


class RepairStatusArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that preserves the shell wrapper's exit-code semantics."""

    def error(self, message: str) -> None:  # pragma: no cover - exercised via main()
        raise UsageError(message)


def _repo_root() -> Path:
    """Resolve the repo root from this engine's location."""
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


def _db_path() -> str:
    """Resolve the Yoke DB path via the canonical worktree-aware resolver.

    This keeps repairs pointed at the owning main-checkout DB when invoked
    from linked worktrees.
    """
    from yoke_core.domain.db_helpers import resolve_db_path

    return resolve_db_path()


def _connect():
    """Open the Yoke authority DB with row access."""
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _normalize_ref(ref: str) -> str:
    """Strip a leading YOK- prefix and normalize numeric refs."""
    cleaned = re.sub(r"^[Yy][Oo][Kk]-", "", ref or "").strip()
    if cleaned.isdigit():
        return str(int(cleaned))
    return cleaned


def _normalize_item_id(ref: str) -> int:
    """Normalize a backlog item ref to an integer ID."""
    cleaned = _normalize_ref(ref)
    if not cleaned.isdigit():
        raise ValueError(f"Item ID must be numeric, got '{ref}'")
    return int(cleaned)


def _normalize_task_num(raw: str) -> int:
    """Parse a task number."""
    try:
        return int(raw)
    except ValueError as exc:  # pragma: no cover - tiny guard
        raise ValueError(f"Task number must be an integer, got '{raw}'") from exc


# Re-export each public repair flow directly from its canonical owner sibling.
# Keep these imports below the helper definitions so sibling lazy imports can
# resolve the shared CLI infrastructure.
from yoke_core.engines.repair_status_item import (  # noqa: E402
    _validate_item_target_status,
    repair_item_status,
)
from yoke_core.engines.repair_status_task import (  # noqa: E402
    repair_task_status,
)


__all__ = [
    "USAGE",
    "UsageError",
    "RepairStatusArgumentParser",
    "_repo_root",
    "_db_path",
    "_connect",
    "_normalize_ref",
    "_normalize_item_id",
    "_normalize_task_num",
    "_validate_item_target_status",
    "repair_item_status",
    "repair_task_status",
    "parse_args",
    "main",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments while preserving the shell command contract."""
    parser = RepairStatusArgumentParser(
        prog="python3 -m yoke_core.engines.repair_status",
        add_help=True,
        usage=USAGE,
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--task", action="store_true")
    parser.add_argument("--reason", default="emergency-repair")
    parser.add_argument("refs", nargs="*")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    try:
        args = parse_args(argv)
    except UsageError as exc:
        print(f"Usage:\n{USAGE}", file=sys.stderr)
        if str(exc):
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.task:
        if len(args.refs) != 3:
            print(f"Usage:\n{USAGE}", file=sys.stderr)
            return 1
        epic_ref, task_num, new_status = args.refs
        return repair_task_status(
            epic_ref,
            task_num,
            new_status,
            dry_run=args.dry_run,
            reason=args.reason,
        )

    if len(args.refs) != 2:
        print(f"Usage:\n{USAGE}", file=sys.stderr)
        return 1

    item_ref, new_status = args.refs
    return repair_item_status(
        item_ref,
        new_status,
        dry_run=args.dry_run,
        reason=args.reason,
    )


if __name__ == "__main__":
    raise SystemExit(main())
