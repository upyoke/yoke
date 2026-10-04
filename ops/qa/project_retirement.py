"""Retire named fixture projects and prove retained history on a deployed API.

The deployment case supplies its subject and endpoint. Every mutation uses
the registered product command and retains retirement blockers as failures.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess


def call(environment, *argv):
    result = subprocess.run(
        ["yoke", "--env", environment, *argv, "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        envelope = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError(f"project_retirement_response_invalid: {argv}") from exc
    if result.returncode or envelope.get("success") is False:
        raise RuntimeError(
            f"project_retirement_probe_refused: {argv}: "
            f"{envelope.get('error') or result.stderr}; resolve the named refusal and rerun"
        )
    return envelope.get("result", envelope)


def prove(environment, projects, expected_active):
    base = os.environ.get("BASE_URL", "").rstrip("/")
    if (
        not base
        or not os.environ.get("DEPLOYMENT_RUN_ID")
        or not os.environ.get("DEPLOYMENT_MEMBER_REF")
    ):
        raise RuntimeError(
            "deployment_qa_subject_missing: run as the deployed member case"
        )
    connection = next(
        row
        for row in call(environment, "env", "list")["rows"]
        if row["env"] == environment
    )
    # Product distribution and its control plane can have different endpoints.
    # The explicit connection owns mutations; BASE_URL identifies the case target.
    if connection["transport"] != "https" or not connection["api_url"]:
        raise RuntimeError(
            "deployment_qa_target_mismatch: use the case's HTTPS connection"
        )
    for project in projects:
        before = call(environment, "projects", "get", "--project", project)["row"]
        call(
            environment,
            "projects",
            "retire",
            "--project",
            str(before["id"]),
            "--reason",
            "Completed machine QA fixture; retain evidence and remove from active inventory",
        )
        after = call(environment, "projects", "get", "--project", str(before["id"]))[
            "row"
        ]
        if not after["retired_at"] or any(
            before[key] != after[key]
            for key in ("id", "slug", "public_item_prefix", "created_at")
        ):
            raise RuntimeError(f"project_retirement_history_changed: {project}")
        print(
            f"retired {project}; project {after['id']} remains directly readable",
            flush=True,
        )
    active = call(environment, "projects", "list")["rows"]
    active_ids = {row["id"] for row in active}
    historical = call(environment, "projects", "list", "--include-retired")["rows"]
    retained = {row["slug"] for row in historical if row["id"] not in active_ids}
    if not set(projects) <= retained:
        raise RuntimeError(
            "project_retirement_inventory_failed: retired fixtures must remain in history"
        )
    prefixes = {
        call(environment, "projects", "get", "--project", str(row["id"]))["row"][
            "public_item_prefix"
        ]
        for row in active
    }
    if prefixes != set(expected_active):
        raise RuntimeError(
            f"project_retirement_active_inventory_failed: active prefixes={sorted(prefixes)}"
        )
    print(
        f"default project inventory: {sorted(prefixes)}; retired fixtures retained",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--projects", nargs="+", required=True)
    parser.add_argument("--expected-active", nargs="+", required=True)
    args = parser.parse_args()
    prove(args.environment, args.projects, args.expected_active)


if __name__ == "__main__":
    main()
