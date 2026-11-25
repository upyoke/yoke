"""Read standalone partition identities without creating requirement rows."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_execution_environment_target import (
    resolve_plan_execution_target,
    target_digest,
)
from yoke_core.domain.qa_latest_execution import latest_verdict_executions
from yoke_core.domain.qa_plan_case_definition import case_baselines, plan_cases
from yoke_core.domain.qa_plan_case_targets import require_single_execution_target
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    marker,
    select_plan_execution,
)
from yoke_core.domain.qa_plan_partition_custody import PartitionScope, case_identity
from yoke_core.domain.qa_plan_partitions import PartitionView, partition_views


def standalone_partition_views(
    conn: Any, plan_id: int, *, source_revision: str | None
) -> list[PartitionView]:
    cases = plan_cases(conn, plan_id)
    if not cases:
        raise QaPlanExecutionStateError(
            "standalone_empty_plan: add cases before running this plan"
        )
    target = resolve_plan_execution_target(conn, plan_id=plan_id)
    require_single_execution_target(cases, target)
    digest = target_digest(target)
    roster = sorted(
        (
            {
                **case,
                "method_config": json.loads(case["method_config"] or "{}"),
                "host_baselines": json.loads(case["host_baselines"] or "[]"),
                "host_baseline": baseline,
                "baseline_position": position,
                "execution_target_digest": digest,
            }
            for case in cases
            for position, baseline in enumerate(case_baselines(case), 1)
        ),
        key=lambda row: (row["baseline_position"], row["position"]),
    )
    scope = PartitionScope(standalone_plan_id=plan_id)
    verdicts = _standalone_verdicts(conn, scope, digest, source_revision)
    return partition_views(
        conn, scope, roster,
        passed={identity for identity, verdict in verdicts.items() if verdict == "pass"},
        failed={identity for identity, verdict in verdicts.items() if verdict == "fail"},
    )


def _standalone_verdicts(
    conn: Any, scope: PartitionScope, digest: str, source_revision: str | None
) -> dict[tuple, str | None]:
    if source_revision is None:
        return {}
    p = marker(conn)
    rows = query_rows(
        conn,
        "SELECT id FROM qa_plan_executions "
        f"WHERE standalone_plan_id={p} AND execution_target_digest={p} "
        "AND state IN ('completed','aborted','error') ORDER BY execution_order DESC",
        (scope.standalone_plan_id, digest),
    )
    verdicts = {}
    for row in rows:
        execution = select_plan_execution(conn, str(row["id"]), lock=False)
        cases = {
            int(case["requirement_id"]): case_identity(case, scope)
            for case in execution["roster"]
            if case.get("standalone_source_revision") == source_revision.lower()
        }
        for requirement, attempt in latest_verdict_executions(conn, cases).items():
            verdicts.setdefault(cases[requirement], attempt["verdict"])
    return verdicts
