"""QA → screenshot evidence satisfaction bridge.

Owns ``cmd_satisfy_screenshot_evidence`` — bridges inspection-verified
browser captures into ``ac_verification`` requirement passes for items
whose ``success_policy`` carries the ``requires_screenshot_evidence``
token. The capture-guard exits with code **3** (not 1) when no
inspection-verified browser run is found; downstream consumers
distinguish 3 from 1 when interpreting the failure.
"""

from __future__ import annotations

import sys
from typing import Optional

from yoke_core.domain.db_helpers import (
    connect,
    iso8601_now,
    query_rows,
    query_scalar,
)


def cmd_satisfy_screenshot_evidence(
    *,
    db_path: Optional[str] = None,
    item_id: int,
    evidence: str = "Browser QA screenshot evaluation passed -- screenshots consistent with acceptance criteria",
) -> int:
    """Satisfy ac_verification requirements with [requires_screenshot_evidence].

    Returns count of newly satisfied requirements. Prints ``0`` and returns
    when no requirements need satisfying. Refuses to insert the
    ac_verification pass row unless the item has at least one
    inspection-verified browser capture — a ``browser_smoke`` or
    ``browser_diff`` qa_run with ``execution_status='captured'`` AND
    ``verdict='pass'``.
    """
    if not item_id:
        print("Error: --item-id is required", file=sys.stderr)
        sys.exit(2)

    conn = connect(path=db_path)
    try:
        # guard: require an inspection-verified capture before bridging.
        inspected_count = query_scalar(conn, """
            SELECT COUNT(*) FROM qa_runs qr
            JOIN qa_requirements r ON r.id = qr.qa_requirement_id
            WHERE r.item_id = %s
              AND r.qa_kind IN ('browser_smoke','browser_diff')
              AND qr.executor_type = 'browser_substrate'
              AND qr.execution_status = 'captured'
              AND qr.verdict = 'pass'
        """, (item_id,))
        if not inspected_count or int(inspected_count) == 0:
            print(
                f"Error: item {item_id} has no inspection-verified browser captures "
                "(need execution_status='captured' AND verdict='pass' on a "
                "browser_smoke/browser_diff run). Call "
                "`yoke qa run complete --requirement-id <id> "
                "--run-id <capture_run_id> --verdict pass` "
                "after screenshot inspection, then retry.",
                file=sys.stderr,
            )
            sys.exit(3)

        # Find unsatisfied ac_verification requirements with screenshot evidence
        # deliberate case-sensitive match against internal success_policy token
        unsatisfied = query_rows(conn, """
            SELECT r.id, r.success_policy
            FROM qa_requirements r
            WHERE r.item_id = %s
              AND r.qa_kind = 'ac_verification'
              AND r.success_policy LIKE '%%requires_screenshot_evidence%%'
              AND r.waived_at IS NULL
              AND r.id NOT IN (
                SELECT qa_requirement_id FROM qa_runs
                WHERE verdict = 'pass' AND executor_type = 'browser_substrate'
              )
            ORDER BY r.id
        """, (item_id,))

        if not unsatisfied:
            print("0")
            return 0

        for req_row in unsatisfied:
            rid = req_row["id"]
            now_iso = iso8601_now()
            conn.execute(
                """INSERT INTO qa_runs
                    (qa_requirement_id, executor_type, qa_kind, verdict,
                     raw_result, started_at, completed_at, created_at)
                    VALUES (%s, 'browser_substrate', 'ac_verification', 'pass',
                            %s, %s, %s, %s)""",
                (rid, evidence, now_iso, now_iso, now_iso),
            )

        conn.commit()

        # Count how many were satisfied (re-query)
        # deliberate case-sensitive match against internal success_policy token
        count = query_scalar(conn, """
            SELECT COUNT(*) FROM qa_requirements r
            WHERE r.item_id = %s
              AND r.qa_kind = 'ac_verification'
              AND r.success_policy LIKE '%%requires_screenshot_evidence%%'
              AND r.waived_at IS NULL
              AND r.id IN (
                SELECT qa_requirement_id FROM qa_runs
                WHERE verdict = 'pass' AND executor_type = 'browser_substrate'
              )
        """, (item_id,))
    finally:
        conn.close()

    print(count)
    return count
