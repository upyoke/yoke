"""Require the final verdict of an item's pinned Shepherd planning segment.

The lifecycle task-graph gate calls ``check_gate`` for this lookup.
The immutable binding supplies the final edge and its verdict identity.
A workflow with no Shepherd binding has no Shepherd lifecycle obligation.
"""

from __future__ import annotations

from yoke_core.domain.project_identity import render_item_ref

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain import db_helpers
from yoke_core.domain.shepherd_segment import shepherd_edges
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


ACCEPTABLE_VERDICTS = ("READY", "SKIPPED", "CAVEATS")


@dataclass(frozen=True)
class GateResult:
    passed: bool
    transition: Optional[str]
    verdict: Optional[str]
    reason: str


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _lookup_latest_verdict(
    conn: Any,
    public_ref: str,
    transition: str,
) -> Optional[str]:
    p = _placeholder(conn)
    verdict_placeholders = ", ".join([p] * len(ACCEPTABLE_VERDICTS))
    row = db_helpers.query_one(
        conn,
        "SELECT verdict FROM shepherd_verdicts "
        f"WHERE item = {p} AND transition = {p} "
        f"AND verdict IN ({verdict_placeholders}) "
        "AND (verdict <> 'SKIPPED' OR LOWER(worker) IN ('review', 'architect')) "
        "ORDER BY id DESC LIMIT 1",
        (public_ref, transition, *ACCEPTABLE_VERDICTS),
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
    # ``shepherd_verdicts.item`` is keyed by the writer as the legacy
    # ``YOK-{items.id}`` token, so the lookup key and the operator-facing
    # display ref are two different strings.
    verdict_key = f"YOK-{item_id}"

    def _evaluate(c: Any) -> GateResult:
        public_ref = render_item_ref(c, int(item_id))
        edges = shepherd_edges(load_item_workflow_runtime(c, item_id))
        if not edges:
            return GateResult(True, None, None, f"No Shepherd binding on {public_ref}.")
        transition = edges[-1].verdict_key
        current = _lookup_latest_verdict(c, verdict_key, transition)
        if current is not None:
            return GateResult(
                passed=True,
                transition=transition,
                verdict=current,
                reason=f"Gate satisfied by {transition}={current} on {public_ref}.",
            )
        return GateResult(
            passed=False,
            transition=None,
            verdict=None,
            reason=(
                f"No qualifying shepherd verdict for {public_ref}. "
                f"Expected transition '{transition}' in {ACCEPTABLE_VERDICTS!r}. "
                "Resume Shepherd within its binding and persist the final plan review."
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
        from yoke_core.domain.yok_n_parser import parse_item_argument

        try:
            number = parse_item_argument(args.item_id)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
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
