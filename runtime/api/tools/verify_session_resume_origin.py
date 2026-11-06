"""Check a full production day of durable relay attempt records through the CLI."""

from __future__ import annotations

import os
import re
import subprocess


def main() -> int:
    run_id = os.environ.get("DEPLOYMENT_RUN_ID", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise SystemExit(
            "release_run_required: run this case through its deployment QA requirement"
        )
    query = f"""
        WITH delivery AS (
            SELECT MAX(completed_at) AS ready_at FROM deployment_stage_receipts
            WHERE run_id='{run_id}' AND target_name='prod' AND status='ready'
        ), attempts AS (
            SELECT a.target_session_id, s.launch_origin FROM session_message_attempts a
            LEFT JOIN harness_sessions s ON s.session_id=a.target_session_id
            CROSS JOIN delivery d
            WHERE a.attempt_kind='wake_relay' AND a.started_at>=d.ready_at
              AND COALESCE(a.result_code,'') NOT LIKE 'skipped_%'
              AND COALESCE(a.result_code,'') NOT LIKE 'recipient_%'
        )
        SELECT
            CASE WHEN d.ready_at IS NOT NULL AND
                CURRENT_TIMESTAMP>=d.ready_at + INTERVAL '1 day' THEN 1 ELSE 0 END,
            (SELECT COUNT(*) FROM attempts WHERE launch_origin='operator'),
            (SELECT COUNT(*) FROM attempts WHERE launch_origin IS NULL),
            (SELECT COUNT(*) FROM attempts WHERE launch_origin='yoke')
        FROM delivery d
    """
    try:
        result = subprocess.run(
            ["yoke", "db", "read", query, "--format", "lines"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(
            "origin_evidence_timeout: restore production connectivity and rerun this case"
        ) from None
    if result.returncode:
        print(result.stderr or result.stdout)
        raise SystemExit(
            "origin_evidence_unavailable: repair the registered production read and rerun this case"
        )
    fields = result.stdout.strip().split("|")
    if len(fields) != 4 or not all(value.strip().isdigit() for value in fields):
        raise SystemExit(
            "origin_evidence_unreadable: inspect the registered db read output before retrying"
        )
    elapsed, operator, unknown, managed = map(int, fields)
    print(
        f"day_elapsed={elapsed} operator_attempts={operator} unknown_attempts={unknown} yoke_attempts={managed}"
    )
    if not elapsed or not managed:
        raise SystemExit(
            "origin_observation_pending: park until a full day after production delivery with real relay traffic"
        )
    if operator or unknown:
        raise SystemExit(
            "unauthorized_resume: inspect session message attempts and repair origin authority before accepting delivery"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
