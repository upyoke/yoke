"""Prove a release takeover sends no wake to a manual-only holder with a recheck.

Reads durable production rows only (session_messages, session_scheduled_wakes,
work_claims, qa_requirements, deployment_runs) through ``yoke db read``.
A candidate is a takeover created after this item's first deployment that
moved a member whose every requirement on the successor is manual-wake and
whose claim holder, at takeover time, held a scheduled wake still due later.
Each candidate must have no ``deployment-qa-moved`` notice.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess

from runtime.api.tools.first_deployment import first_deployment_sql


def read(sql: str) -> dict:
    result = subprocess.run(
        ["yoke", "db", "read", sql, "--format", "json"],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            f"takeover_recheck_read_refused: {result.stderr}; repair the named read and rerun"
        )
    return json.loads(result.stdout)


def candidates_sql(start: str) -> str:
    return (
        "SELECT d.id AS run_id, di.item_id, wc.session_id, "
        "EXISTS (SELECT 1 FROM session_messages m WHERE m.idempotency_key="
        "'deployment-qa-moved:' || d.id || ':' || di.item_id) AS woken "
        "FROM deployment_runs d JOIN deployment_run_items di ON di.run_id=d.id "
        "JOIN work_claims wc ON wc.target_kind='item' "
        "AND (CAST(wc.scope AS jsonb)->>'item_id')::bigint=di.item_id "
        "AND wc.claimed_at<=d.created_at "
        "AND (wc.released_at IS NULL OR wc.released_at>d.created_at) "
        f"WHERE d.supersedes_run_id IS NOT NULL AND d.created_at>={start} "
        "AND EXISTS (SELECT 1 FROM session_scheduled_wakes w "
        "WHERE w.session_id=wc.session_id AND w.created_at<=d.created_at "
        "AND w.due_at>d.created_at) "
        "AND EXISTS (SELECT 1 FROM qa_requirements q WHERE q.deployment_run_id=d.id "
        "AND q.deployment_member_item_id=di.item_id) "
        "AND NOT EXISTS (SELECT 1 FROM qa_requirements q WHERE q.deployment_run_id=d.id "
        "AND q.deployment_member_item_id=di.item_id "
        "AND q.wake_path IS DISTINCT FROM 'manual') "
        "ORDER BY d.created_at, di.item_id"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-id", type=int, required=True)
    args = parser.parse_args()
    run_id = os.environ.get("DEPLOYMENT_RUN_ID", "")
    if not run_id:
        raise ValueError(
            "takeover_recheck_run_unbound: run this through its post-deploy QA case"
        )
    quoted = "'" + run_id.replace("'", "''") + "'"
    start = first_deployment_sql(quoted, f"q.plan_id={int(args.plan_id)}")
    report = read(candidates_sql(start))
    if report.get("truncated"):
        raise ValueError(
            "takeover_recheck_evidence_truncated: narrow the read and rerun"
        )
    rows = [dict(zip(report["columns"], row, strict=True)) for row in report["rows"]]
    print(json.dumps(rows, sort_keys=True, default=str))
    if not rows:
        raise ValueError(
            "takeover_recheck_observation_pending: no takeover after this release has "
            "moved a manual-only member whose holder held a scheduled recheck; "
            "schedule your next recheck with yoke sessions wake schedule --at "
            "INSTANT --reason TEXT, then park"
        )
    woken = [row for row in rows if row["woken"]]
    if woken:
        raise ValueError(
            f"takeover_recheck_regression: {len(woken)} takeover notice(s) reached "
            "holders that held a scheduled recheck: "
            + ", ".join(f"{row['run_id']}:{row['item_id']}" for row in woken)
            + "; inspect deployment_qa_takeover_notice.recheck_holding_members"
        )
    print(f"takeover_recheck_skip_proven: {len(rows)} skipped holder(s)")


if __name__ == "__main__":
    main()
