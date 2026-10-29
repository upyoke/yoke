"""Bounded human overview of a deployment run; explicit reads own detail."""

from collections.abc import Mapping
from typing import Any, TextIO

from yoke_cli.transport.human_values import write_human


def write_run_summary(result: Mapping[str, Any], stdout: TextIO) -> None:
    run = result.get("run") or {}
    run_id = result.get("run_id") or run.get("id")
    summary = {
        key: run[key]
        for key in (
            "id", "project", "flow", "target_environment", "status",
            "current_stage", "release_lineage", "composition_frozen_at",
        )
        if key in run
    }
    # Missing computed membership on older serving builds is unknown, never zero.
    for field, label in (
        ("member_items", "member_count"),
        ("membership_removals", "removed_member_count"),
    ):
        summary[label] = len(run[field]) if field in run else "unavailable"
    summary["attestation_warning_count"] = len(result.get("attestation_warnings") or [])
    write_human({"run_id": run_id, "run": summary}, stdout)
    print(f"Members: yoke deployment-runs get {run_id} member_items membership_removals", file=stdout)
    print(f"Blockers: yoke deployment-runs get {run_id} --include-member-closure --json", file=stdout)
    print(f"Details: yoke deployment-runs get {run_id} FIELD ... or --full", file=stdout)
