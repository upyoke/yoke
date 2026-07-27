from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)


CATALOG_CASES = [
    {
        "case_key": "backend-suite",
        "position": 1,
        "method_id": "command",
        "instructions": "Run the registered backend suite.",
        "expected_outcome": "The suite exits successfully.",
        "method_config": {"command": "python3 -m pytest runtime/api"},
    },
    {
        "case_key": "checkout-flow",
        "position": 2,
        "method_id": "browser-check",
        "instructions": "Open checkout and submit the declared fixture.",
        "expected_outcome": "The confirmation route and summary are visible.",
        "method_config": {
            "base_url": "http://localhost:9999",
            "steps": [
                {"action": "navigate", "route": "/checkout"},
                {"action": "assert", "target": "main", "check": "visible"},
            ],
        },
    },
]


def create_release_readiness_plan(conn: Any) -> dict[str, Any]:
    plan = create_plan(
        conn,
        project="yoke",
        slug="release-readiness",
        name="Release readiness",
    )
    replace_plan_cases(conn, plan_id=plan["id"], cases=CATALOG_CASES)
    return plan
