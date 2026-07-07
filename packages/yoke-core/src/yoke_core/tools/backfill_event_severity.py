"""One-shot severity relabel for existing rows of a single event_name.

When an event's declared severity changes (e.g. HookGuardrailEvaluated
INFO -> DEBUG), the rows already in the table keep their old severity and
so escape the new retention tier. This tool relabels existing rows so the
prune's per-severity age rule applies to the backlog too.

Scoped to ONE event_name and ONE target severity, with a dry-run default
and explicit --apply. Operator/debug tool; not an agent surface.

    python3 -m yoke_core.tools.backfill_event_severity \
        --event HookGuardrailEvaluated --to DEBUG [--apply]
"""

from __future__ import annotations

import argparse
import sys

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect

_VALID = ("DEBUG", "INFO", "STATUS", "WARN", "ERROR", "FATAL")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m yoke_core.tools.backfill_event_severity")
    p.add_argument("--event", required=True, help="event_name to relabel")
    p.add_argument("--to", required=True, choices=_VALID, help="target severity")
    p.add_argument("--apply", action="store_true",
                   help="Without this flag, only report what would change.")
    args = p.parse_args(argv)

    conn = connect()
    try:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        before = conn.execute(
            f"SELECT severity, COUNT(*) AS n FROM events WHERE event_name={marker} "
            "GROUP BY severity ORDER BY n DESC",
            (args.event,),
        ).fetchall()
        print(f"event: {args.event}  target severity: {args.to}")
        print("before:")
        total_to_change = 0
        for row in before:
            sev = row["severity"]
            n = row["n"]
            print(f"  {sev}: {n}")
            if sev != args.to:
                total_to_change += n
        if not before:
            print("  (no rows for this event_name)")
            return 0
        print(f"rows that would change to {args.to}: {total_to_change}")

        if not args.apply:
            print("DRY-RUN: pass --apply to perform the UPDATE.")
            return 0

        cur = conn.execute(
            "UPDATE events SET "
            f"severity={marker} WHERE event_name={marker} AND severity<>{marker}",
            (args.to, args.event, args.to),
        )
        changed = cur.rowcount if cur.rowcount is not None else 0
        conn.commit()
        print(f"APPLIED: relabeled {changed} rows to {args.to}.")

        after = conn.execute(
            f"SELECT severity, COUNT(*) AS n FROM events WHERE event_name={marker} "
            "GROUP BY severity ORDER BY n DESC",
            (args.event,),
        ).fetchall()
        print("after:")
        for row in after:
            print(f"  {row['severity']}: {row['n']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
