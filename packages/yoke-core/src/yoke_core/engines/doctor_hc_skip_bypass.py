"""Doctor HC for detecting manual polish-skip anti-patterns.

``/yoke advance YOK-N --skip-polish`` is the canonical surface for
collapsing ``reviewed-implementation -> polishing-implementation ->
implemented`` into a single sanctioned hop.  Before this flag existed,
operators sometimes achieved the same transition by running two manual
``items update ... status`` calls in quick succession — a pattern that
bypasses skip accounting (no ``SkipHopPerformed`` record, no ``via`` tag)
and re-introduces the raw lifecycle mutation that
``# lint:no-lifecycle-mutation-check`` exists to prevent.

This health check surfaces lingering or future uses of that pattern so
the canonical ``--skip-polish`` path stays canonical.

Heuristic: within the past 30 days, look for pairs of
``item_status_transitions`` rows on the same ``item_id`` where

* the first transitions ``reviewed-implementation -> polishing-implementation``,
* the second transitions ``polishing-implementation -> implemented``,
* both carry ``source=backlog-registry`` (the default for raw ``items
  update`` writes — NOT ``skip-polish`` and NOT a dedicated polish skill
  source),
* the gap between them is under 60 seconds (genuine polish work takes
  longer; sub-minute sequences are bookkeeping, not review).

Emits a WARN with the affected item ids and a suggestion to use
``--skip-polish`` going forward.  PASS when no such sequences exist.
"""

from __future__ import annotations

from typing import List

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.time_sql import now_sql

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-skip-polish-manual-hop"
_HC_DESC = "Manual polish-skip bookkeeping hops that should use --skip-polish"
_GAP_SECONDS_SQL = (
    "EXTRACT(EPOCH FROM ((b.created_at)::timestamp - (a.created_at)::timestamp))"
)


def hc_skip_polish_manual_hop(
    conn, args: DoctorArgs, rec: RecordCollector
) -> None:
    """Flag ``reviewed-implementation -> polishing-implementation -> implemented``
    sequences performed via raw ``items update`` that should have used
    ``/yoke advance YOK-N --skip-polish``.
    """
    if not _base._table_exists(conn, "item_status_transitions"):
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "item_status_transitions table missing — skipping",
        )
        return

    # Pair up consecutive item-level transition rows per item_id within
    # the last 30 days. The transition pair of interest is:
    #   reviewed-implementation -> polishing-implementation  (row A)
    #   polishing-implementation -> implemented              (row B)
    # both with source=backlog-registry, A and B < 60s apart.
    rows = query_rows(
        conn,
        f"""
        WITH lifecycle AS (
            SELECT t.item_id, t.created_at, t.from_status, t.to_status,
                   t.source AS src
            FROM item_status_transitions t
            WHERE t.task_num IS NULL
              AND t.created_at >= {now_sql(offset_days=-30)}
        )
        SELECT
            a.item_id,
            a.created_at AS a_at,
            b.created_at AS b_at,
            {_GAP_SECONDS_SQL} AS gap_s
        FROM lifecycle a
        JOIN lifecycle b
          ON a.item_id = b.item_id
         AND b.created_at > a.created_at
        WHERE a.from_status = 'reviewed-implementation'
          AND a.to_status   = 'polishing-implementation'
          AND a.src         = 'backlog-registry'
          AND b.from_status = 'polishing-implementation'
          AND b.to_status   = 'implemented'
          AND b.src         = 'backlog-registry'
          AND {_GAP_SECONDS_SQL} <= 60
        ORDER BY a.created_at DESC
        LIMIT 20
        """,
    )

    if not rows:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return

    issues: List[str] = [
        f"- {len(rows)} sequence(s) in the last 30 days look like manual "
        "polish skips (raw items update through polishing-implementation). "
        "Use `/yoke advance YOK-N --skip-polish` instead — it emits "
        "a single `SkipHopPerformed` event and keeps the claim lifecycle "
        "honest.",
    ]
    for row in rows[:10]:
        item = row["item_id"]
        gap = int(row["gap_s"] or 0)
        issues.append(
            f"  - YOK-{item}: reviewed-implementation -> "
            f"polishing-implementation -> implemented in {gap}s "
            f"(at {row['a_at']})"
        )
    if len(rows) > 10:
        issues.append(f"  - ... and {len(rows) - 10} more")

    rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(issues))
