"""Doctor HC for false-reject path-claim registrations.

Surfaces ``PathClaimRegistrationBlocked`` events whose candidate item
already had dependency edges to every overlapping upstream item at the
time of rejection. After the
``register_for_item`` fix that threads ``candidate_item_id`` through
``classify_overlap`` and auto-resolves the upstream via
``auto_resolve_upstream``, this combination should never appear — the
classifier is supposed to land the candidate in ``state='blocked'``
rather than reject. A non-empty result indicates regression of that
wiring (some new code path dropped ``candidate_item_id`` again).

Look-back: 24 hours. PASS when no candidate cases are
present.
"""

from __future__ import annotations

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.sql_json import json_get
from yoke_core.domain.time_sql import now_sql

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-path-claim-register-rejected-with-deps"
_HC_DESC = (
    "PathClaimRegistrationBlocked rejections where the candidate already "
    "declared item_dependencies to overlapping upstream items"
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_path_claim_register_rejected_with_deps(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Flag false-reject registration events that the dep-graph
    awareness branch in :func:`classify_overlap` should have absorbed.
    """
    if not _base._table_exists(conn, "events"):
        rec.record(_HC_NAME, _HC_DESC, "PASS", "events table missing — skipping")
        return
    if not _base._table_exists(conn, "item_dependencies"):
        rec.record(_HC_NAME, _HC_DESC, "PASS", "item_dependencies missing — skipping")
        return
    if not _base._table_exists(conn, "path_claims"):
        rec.record(_HC_NAME, _HC_DESC, "PASS", "path_claims missing — skipping")
        return

    blocking_expr = json_get('e.envelope', '$.context.blocking_claim_id')
    rows = query_rows(
        conn,
        f"""
        SELECT
            e.item_id AS item_id,
            e.created_at AS at,
            {json_get('e.envelope', '$.context.reason')} AS reason,
            {blocking_expr} AS blocking_claim_id
        FROM events e
        WHERE e.event_name = 'PathClaimRegistrationBlocked'
          AND e.created_at >= {now_sql(offset_days=-1)}
          AND e.item_id IS NOT NULL
          AND {json_get('e.envelope', '$.context.reason')} LIKE '%%overlap%%'
          AND {blocking_expr} IS NOT NULL
        ORDER BY e.created_at DESC
        LIMIT 50
        """,
    )

    flagged: list[dict] = []
    for row in rows:
        item_id = row["item_id"]
        blocking_claim_id = row["blocking_claim_id"]
        if item_id is None or blocking_claim_id is None:
            continue
        placeholder = _p(conn)
        blocking_row = conn.execute(
            f"SELECT item_id FROM path_claims WHERE id = {placeholder}",
            (int(blocking_claim_id),),
        ).fetchone()
        if blocking_row is None or blocking_row[0] is None:
            continue
        ref_a = f"YOK-{int(item_id)}"
        ref_b = str(int(item_id))
        upstream_a = f"YOK-{int(blocking_row[0])}"
        upstream_b = str(int(blocking_row[0]))
        edge_row = conn.execute(
            "SELECT 1 FROM item_dependencies "
            f"WHERE dependent_item IN ({placeholder}, {placeholder}) "
            f"AND blocking_item IN ({placeholder}, {placeholder}) LIMIT 1",
            (ref_a, ref_b, upstream_a, upstream_b),
        ).fetchone()
        if edge_row is None:
            continue
        flagged.append(row)

    if not flagged:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return

    issues = [
        f"- {len(flagged)} PathClaimRegistrationBlocked event(s) in the last "
        "24h whose candidate item already had item_dependencies edges "
        "to every overlapping upstream item. The dep-graph branch in classify_overlap "
        "should have classified these as SERIAL_VIA_DEPENDENCY rather "
        "than rejecting. Confirm the on-ramp still threads "
        "candidate_item_id through register_for_item / "
        "path_claims.register and the auto_resolve_upstream call site is "
        "still active.",
    ]
    for row in flagged[:10]:
        item = int(row["item_id"])
        issues.append(
            f"  - YOK-{item} at {row['at']} "
            f"(blocking claim {row['blocking_claim_id']}): {row['reason']}"
        )
    if len(flagged) > 10:
        issues.append(f"  - ... and {len(flagged) - 10} more")

    rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(issues))
