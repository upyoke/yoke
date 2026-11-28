"""Docket lookups for walk-end cleanup: the mission case, its run and host."""

from __future__ import annotations

import json
from typing import Any


def cleanup_mission(conn: Any, execution: dict, requirement_id: int) -> tuple[int, dict, int]:
    from yoke_core.domain.qa_plan_execution_store import result_rows

    matches = [
        (ordinal, case)
        for ordinal, case in enumerate(execution["roster"])
        if int(case["requirement_id"]) == requirement_id
        and case.get("runner_id") == "agent_mission"
    ]
    results = [
        r
        for r in result_rows(conn, str(execution["id"]))
        if r["requirement_id"] == requirement_id
    ]
    if len(matches) != 1 or len(results) != 1:
        raise ValueError(
            "mission_cleanup_docket_missing: no recorded mission matches this "
            "execution; ask the control-plane operator to inspect its docket"
        )
    ordinal, case = matches[0]
    return ordinal, case, int(results[0]["result"]["run_id"])


def original_host(conn: Any, run_id: int) -> str:
    from yoke_core.domain.coordination_claims import get_claim
    from yoke_core.domain.db_helpers import query_one

    row = query_one(conn, "SELECT raw_result FROM qa_runs WHERE id=%s", (run_id,))
    raw = json.loads(row["raw_result"]) if row else {}
    lease_id = raw.get("host_control_submission", {}).get("lease_id")
    if not lease_id:
        raise ValueError(
            "mission_cleanup_host_unknown: the docket has no original lease; "
            "ask the control-plane operator to recover the host identity"
        )
    test_machine = get_claim(conn, int(lease_id)).target.test_machine
    if not test_machine:
        raise ValueError("mission_cleanup_host_unknown: inspect the docket's lease")
    return str(test_machine)
