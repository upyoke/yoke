"""Explain how a failed QA retry differs from shipping a code correction."""

from typing import Any


def pinned_source_guidance(conn: Any, run_id: str) -> str:
    row = conn.execute(
        "SELECT release_lineage FROM deployment_runs WHERE id=%s", (str(run_id),)
    ).fetchone()
    source = str(row[0] or "") if row else ""
    if not source:
        raise ValueError(
            f"deployment_run_source_unavailable: run {run_id} has no pinned source commit; "
            f"inspect `yoke deployment-runs get {run_id}` before choosing recovery"
        )
    return (
        f"Pinned source commit: {source}. Retry reruns on that commit for environment "
        "or flaky failures only. A code fix needs a merge followed by a new run on a "
        f"later commit; that run takes over {run_id}. Waive discharges the named "
        "requirement with authorization; remove detaches the item from this run "
        "and leaves its delivery owed."
    )
