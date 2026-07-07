"""CLI entrypoint for ``python3 -m yoke_core.domain.path_integrity_repair``.

Subcommands:

* ``apply --failure-id N [--operation OP] [--dry-run]`` — apply the
  default repair for a failure, or the explicitly named operation.
* ``abandon --failure-id N --reason TEXT`` — operator-only abandon
  flow recording the reason on the audit row.

Exit codes:

* ``0`` — repair applied or abandoned successfully.
* ``2`` — repair refused (unknown operation, missing failure, etc.).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any


def _connect() -> Any:
    from yoke_core.domain.schema_common import (
        _connect_raw, _resolve_db_path,
    )
    return _connect_raw(_resolve_db_path())


def main(argv=None) -> int:
    from yoke_core.domain.path_integrity_repair import (
        PathIntegrityRepairError, apply_repair, mark_failure_abandoned,
    )

    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.path_integrity_repair",
        description=(
            "Apply or abandon a path-integrity repair operation. "
            "Repairs are limited to substrate reconciliation for "
            "verifier-emitted failures."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_apply = sub.add_parser(
        "apply", help="Apply the default repair for a failure.",
    )
    p_apply.add_argument("--failure-id", type=int, required=True)
    p_apply.add_argument("--operation", default=None)
    p_apply.add_argument("--dry-run", action="store_true")

    p_abandon = sub.add_parser(
        "abandon",
        help="Mark a failure abandoned with a recorded reason.",
    )
    p_abandon.add_argument("--failure-id", type=int, required=True)
    p_abandon.add_argument("--reason", required=True)

    args = parser.parse_args(argv)

    conn = _connect()
    try:
        if args.command == "apply":
            try:
                rid = apply_repair(
                    conn, failure_id=args.failure_id,
                    operation=args.operation, dry_run=args.dry_run,
                )
            except PathIntegrityRepairError as exc:
                print(f"REFUSED: {exc}", file=sys.stderr)
                return 2
            print(f"repair #{rid} applied")
            return 0
        if args.command == "abandon":
            try:
                rid = mark_failure_abandoned(
                    conn, failure_id=args.failure_id,
                    reason=args.reason,
                )
            except PathIntegrityRepairError as exc:
                print(f"REFUSED: {exc}", file=sys.stderr)
                return 2
            print(f"repair #{rid} abandoned")
            return 0
    finally:
        conn.close()
    return 2


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
