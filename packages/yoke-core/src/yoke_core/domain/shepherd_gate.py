"""Advance preflight — Shepherd Lifecycle Gate.

Python owner for the advance preflight "Shepherd Lifecycle Gate" described in
``.agents/skills/yoke/advance/preflight-checks.md``. The gate fires when an
epic is advancing to ``implementing`` or later and verifies the shepherd
pipeline signed off on the plan before any implementation work begins.

Modern shepherd writes ``planning_to_plan_drafted`` as its terminal verdict
(via ``cmd_verdict`` in ``yoke_core.domain.shepherd``). The gate accepts
that verdict in ``READY``, ``SKIPPED``, or ``CAVEATS`` state.

Historical epics (pre-2026-04-07, before the shepherd/refine split) used
``planned_to_ready`` as the sign-off verdict. We accept it as a legacy
fallback so those historical epics and any re-runs against their branches
still pass. No producer writes this name today.

CLI::

    python3 -m yoke_core.domain.shepherd_gate check <item-id>

Exits ``0`` when the gate passes, ``1`` when it blocks, ``2`` on argument or
lookup error. Prints a single human-readable line on stdout describing the
outcome — callers can capture it or rely solely on the exit code.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain import db_helpers


CURRENT_TRANSITION = "planning_to_plan_drafted"
# Historical compat: pre-2026-04-07 shepherd wrote this name. No modern
# producer writes it. Kept so epics that passed the pre-split pipeline still
# satisfy the gate without --force.
LEGACY_TRANSITION = "planned_to_ready"
ACCEPTABLE_VERDICTS = ("READY", "SKIPPED", "CAVEATS")


@dataclass(frozen=True)
class GateResult:
    passed: bool
    transition: Optional[str]
    verdict: Optional[str]
    reason: str


def _normalize_item_id(raw: str) -> Optional[int]:
    stripped = raw.strip()
    if stripped.upper().startswith("YOK-"):
        stripped = stripped[4:]
    stripped = stripped.lstrip("0")
    if stripped == "":
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _lookup_latest_verdict(
    conn: Any,
    item_ref: str,
    transition: str,
) -> Optional[str]:
    p = _placeholder(conn)
    verdict_placeholders = ", ".join([p] * len(ACCEPTABLE_VERDICTS))
    row = db_helpers.query_one(
        conn,
        "SELECT verdict FROM shepherd_verdicts "
        f"WHERE item = {p} AND transition = {p} "
        f"AND verdict IN ({verdict_placeholders}) "
        "ORDER BY id DESC LIMIT 1",
        (item_ref, transition, *ACCEPTABLE_VERDICTS),
    )
    if row is None:
        return None
    return row[0]


def check_gate(
    item_id: int,
    conn: Optional[Any] = None,
) -> GateResult:
    """Evaluate the Shepherd Lifecycle Gate for a single item.

    Accepts either a caller-managed connection or opens a new one via
    ``db_helpers.connect``. Ownership of a caller-supplied connection is
    preserved — this function neither commits nor closes it.
    """
    item_ref = f"YOK-{item_id}"

    def _evaluate(c: Any) -> GateResult:
        current = _lookup_latest_verdict(c, item_ref, CURRENT_TRANSITION)
        if current is not None:
            return GateResult(
                passed=True,
                transition=CURRENT_TRANSITION,
                verdict=current,
                reason=(
                    f"Gate satisfied by {CURRENT_TRANSITION}={current} "
                    f"on {item_ref}."
                ),
            )
        legacy = _lookup_latest_verdict(c, item_ref, LEGACY_TRANSITION)
        if legacy is not None:
            return GateResult(
                passed=True,
                transition=LEGACY_TRANSITION,
                verdict=legacy,
                reason=(
                    f"Gate satisfied by legacy {LEGACY_TRANSITION}={legacy} "
                    f"on {item_ref} (pre-2026-04-07 compat)."
                ),
            )
        return GateResult(
            passed=False,
            transition=None,
            verdict=None,
            reason=(
                f"No qualifying shepherd verdict for {item_ref}. "
                f"Expected transition '{CURRENT_TRANSITION}' in "
                f"{ACCEPTABLE_VERDICTS!r} (legacy '{LEGACY_TRANSITION}' also "
                f"accepted for pre-2026-04-07 compat)."
            ),
        )

    if conn is not None:
        return _evaluate(conn)
    with db_helpers.connect() as owned:
        return _evaluate(owned)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="shepherd_gate")
    sub = parser.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("check", help="Evaluate gate for one item")
    check.add_argument("item_id", help="Item ID (YOK-N or N)")

    args = parser.parse_args(argv)

    if args.cmd == "check":
        number = _normalize_item_id(args.item_id)
        if number is None:
            print(
                f"Error: could not parse item ID from {args.item_id}",
                file=sys.stderr,
            )
            return 2
        try:
            result = check_gate(number)
        except Exception as exc:
            print(f"Error: shepherd_gate check failed: {exc}", file=sys.stderr)
            return 2
        print(result.reason)
        return 0 if result.passed else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
