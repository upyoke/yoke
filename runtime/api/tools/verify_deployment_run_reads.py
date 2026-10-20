"""Prove deployed run field selection and bounded CLI summary transport."""

from __future__ import annotations

import json
import os
import subprocess
from yoke_cli.transport.output_limit import REPLY_LIMIT_BYTES


def read(*arguments: str) -> dict:
    completed = subprocess.run(
        ["yoke", "deployment-runs", *arguments, "--json"],
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    if completed.returncode:
        raise RuntimeError(
            "deployment_run_read_probe_failed: "
            + completed.stderr
            + "; inspect the named serving refusal and retry this same QA case"
        )
    if len((completed.stdout + completed.stderr).encode()) > REPLY_LIMIT_BYTES:
        raise RuntimeError(
            "deployment_run_read_probe_oversized: repair page budgeting and rerun this case"
        )
    response = json.loads(completed.stdout)
    if response.get("saved_response"):
        from pathlib import Path

        response = json.loads(Path(response["saved_response"]).read_text())["response"]
    if not response.get("success"):
        raise RuntimeError(
            "deployment_run_read_probe_refused: inspect the recorded response and rerun this case"
        )
    return response["result"]


def main() -> None:
    run_id = os.environ.get("DEPLOYMENT_RUN_ID")
    if not run_id:
        raise SystemExit(
            "deployment_run_read_probe_unbound: run through the deployment member QA case"
        )
    fields = ["project", "status", "current_stage", "release_lineage"]
    selected = read("get", run_id, *fields)
    if selected.get("fields") != fields or set(selected.get("run", {})) != set(fields):
        raise SystemExit(
            "deployment_run_read_probe_selection: upgrade the serving field-selection contract and rerun"
        )
    project = selected["run"]["project"]
    first = read("list", "--project", project)
    if not first.get("detail_recipe") or any(
        "carried_work" in row for row in first["rows"]
    ):
        raise SystemExit(
            "deployment_run_read_probe_summary: repair the served summary projection and rerun"
        )
    cursor = first.get("next_cursor")
    if cursor:
        second = read("list", "--project", project, "--cursor", cursor)
        if {row["id"] for row in first["rows"]} & {row["id"] for row in second["rows"]}:
            raise SystemExit(
                "deployment_run_read_probe_cursor: repair continuation and rerun"
            )
    print(
        f"PASS: selected {len(fields)} fields; summary rows={len(first['rows'])}; continuation_checked={bool(cursor)}"
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(
            f"deployment_run_read_probe_failed: {exc}; repair the named read and rerun this same QA case"
        ) from None
