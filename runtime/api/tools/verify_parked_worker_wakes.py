"""Read durable production wake receipts across a full day after deployment."""

from __future__ import annotations

import json
import os
import subprocess


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
            f"parked_wake_read_refused: {result.stderr}; repair the named read and rerun"
        )
    return json.loads(result.stdout)


def main() -> None:
    run_id = os.environ.get("DEPLOYMENT_RUN_ID", "")
    if not run_id:
        raise ValueError(
            "parked_wake_run_unbound: run this through its post-deploy QA case"
        )
    quoted = "'" + run_id.replace("'", "''") + "'"
    # Receipts are durable deployment facts; telemetry retention proves nothing.
    start = (
        "(SELECT MAX(completed_at) FROM deployment_stage_receipts "
        f"WHERE run_id={quoted} AND status='ready')"
    )
    report = read(
        f"SELECT {start} AS deployed_at, CURRENT_TIMESTAMP AS checked_at, "
        f"CURRENT_TIMESTAMP >= {start} + INTERVAL '1 day' AS day_complete, "
        "(SELECT COUNT(*) FROM session_messages m "
        "JOIN session_message_recipients r ON r.message_id=m.message_id "
        "WHERE m.idempotency_key LIKE 'deployment-qa-stage-wait:%:manual-%' "
        f"AND m.created_at >= {start} AND r.wake_attempt_count > 0) AS obsolete_wakes, "
        "(SELECT COUNT(*) FROM deployment_runs d JOIN qa_requirements q "
        "ON q.deployment_run_id=d.id WHERE d.supersedes_run_id IS NOT NULL "
        f"AND d.created_at >= {start} AND q.wake_path='manual') AS takeover_requirements"
    )
    if report.get("truncated") or len(report.get("rows", [])) != 1:
        raise ValueError(
            "parked_wake_evidence_unavailable: restore the bounded production read and rerun"
        )
    facts = dict(zip(report["columns"], report["rows"][0], strict=True))
    print(json.dumps(facts, sort_keys=True))
    if not facts["day_complete"] or not facts["takeover_requirements"]:
        raise ValueError(
            "parked_wake_observation_pending: wait for a full day after deployment "
            "and a real manual-QA takeover; schedule the earliest useful recheck "
            "with yoke sessions wake schedule --at INSTANT --reason TEXT, then park"
        )
    if facts["obsolete_wakes"]:
        raise ValueError(
            "parked_wake_takeover_regression: inspect the durable manual wake receipts, "
            "repair run-based notice identity, and rerun this QA case"
        )
    print(
        "PASS: full production day with manual-QA takeover and no run-based manual wake"
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(str(exc)) from None
