"""Read-only production proof of event attribution and project-less session reads."""

from __future__ import annotations

import json
import subprocess
import tempfile


def call(*args: str, cwd: str | None = None):
    result = subprocess.run(
        ["yoke", "--env", "prod", *args, "--json"],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise SystemExit(
            "events_proof_read_failed: retry the registered read; " + result.stderr
        )
    value = json.loads(result.stdout)
    if not value.get("success"):
        raise SystemExit(
            "events_proof_read_failed: check the registered read's error: "
            + result.stdout
        )
    payload = value["result"]
    if "columns" in payload:
        payload["rows"] = [
            dict(zip(payload["columns"], row)) for row in payload["rows"]
        ]
    return payload


def main() -> None:
    rows = call(
        "db",
        "read",
        "SELECT event_name, COUNT(*) AS total, "
        "COUNT(*) FILTER (WHERE e.project_id IS NULL) AS missing "
        "FROM events e LEFT JOIN harness_sessions s ON s.session_id=e.session_id "
        "WHERE e.created_at >= NOW() - INTERVAL '1 hour' AND "
        "(e.event_name IN ('HarnessToolCallStarted','ItemStatusChanged') OR "
        "(e.event_name='YokeFunctionCalled' AND s.project_id IS NOT NULL)) "
        "GROUP BY event_name",
    )
    print(json.dumps(rows))
    # db.read's registered result contains typed rows.
    sample = rows["rows"]
    if {r["event_name"] for r in sample} != {
        "HarnessToolCallStarted",
        "ItemStatusChanged",
        "YokeFunctionCalled",
    }:
        raise SystemExit(
            "events_proof_sample_missing: wait for each named event in a one-hour post-deploy window, then rerun"
        )
    if any(int(r["missing"]) for r in sample):
        raise SystemExit(
            "events_project_attribution_missing: inspect the listed event producers and rerun after correction"
        )
    columns = call(
        "db",
        "read",
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='events' AND column_name='org_id'",
    )
    if columns["rows"]:
        raise SystemExit(
            "events_org_column_remains: ask the release operator to converge the governed migration"
        )
    sessions = call(
        "db",
        "read",
        "SELECT e.session_id FROM events e JOIN harness_sessions s "
        "ON s.session_id=e.session_id WHERE s.project_id IS NULL AND e.project_id IS NULL "
        "ORDER BY e.created_at DESC LIMIT 1",
    )["rows"]
    if not sessions:
        raise SystemExit(
            "events_projectless_sample_missing: wait for a project-less session to emit telemetry, then rerun"
        )
    session = sessions[0]["session_id"]
    inside = call("events", "query", "--session", session, "--limit", "10")
    with tempfile.TemporaryDirectory(prefix="event-read-proof-") as directory:
        outside = call(
            "events", "query", "--session", session, "--limit", "10", cwd=directory
        )
    if not inside["rows"] or not outside["rows"]:
        raise SystemExit(
            "events_projectless_read_empty: confirm the proof actor has the org admin role and inspect event authorization"
        )
    print(
        "Event attribution and project-less reads passed inside and outside the checkout."
    )


if __name__ == "__main__":
    main()
