"""Case, requirement, and run builders for method rollup tests."""

from runtime.api.fixtures.backlog_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)


def _method_config(method_id: str) -> dict:
    if method_id == "command":
        return {"command": "python3 -m pytest"}
    if method_id == "browser-check":
        return {
            "steps": [
                {"action": "navigate", "route": "/checkout"},
                {"action": "assert", "target": "main", "check": "visible"},
            ],
        }
    if method_id == "browser-inspection":
        return {
            "steps": [
                {"action": "navigate", "route": "/"},
                {"action": "screenshot", "capture": True},
            ],
        }
    return {}


def _case(
    case_key: str,
    position: int,
    method_id: str,
    *,
    host_baselines: list[str] | None = None,
) -> dict:
    return {
        "case_key": case_key,
        "position": position,
        "method_id": method_id,
        "instructions": f"Exercise {case_key}.",
        "expected_outcome": f"{case_key} succeeds.",
        "method_config": _method_config(method_id),
        "host_baselines": host_baselines or [],
    }


def _requirement(
    conn,
    *,
    item_id: int,
    plan_id: int,
    case_key: str,
    method_id: str,
    created_at: str,
    host_baseline: str | None = None,
    waived_at: str | None = None,
):
    return insert_qa_requirement(
        conn,
        item_id=item_id,
        qa_kind="plan_case",
        requirement_source="flow_derived",
        plan_id=plan_id,
        plan_case_key=case_key,
        method_id=method_id,
        host_baseline=host_baseline,
        waived_at=waived_at,
        created_at=created_at,
    )


def _run(
    conn,
    requirement_id: int,
    *,
    created_at: str,
    verdict: str | None,
    case_outcome: str | None,
):
    return insert_qa_run(
        conn,
        qa_requirement_id=requirement_id,
        performed_by="test_runner",
        qa_kind="plan_case",
        verdict=verdict,
        case_outcome=case_outcome,
        created_at=created_at,
    )
