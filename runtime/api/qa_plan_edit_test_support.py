"""Document builders and CAS helpers for QA plan editing tests."""

from runtime.api.qa_catalog_test_support import CATALOG_CASES
from yoke_core.domain.qa_plan_edit import edit_plan
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)


def _plan(conn, *, slug: str = "release-readiness") -> dict:
    plan = create_plan(
        conn,
        project="yoke",
        slug=slug,
        name="Release readiness",
        description="Initial contract.",
    )
    replace_plan_cases(conn, plan_id=plan["id"], cases=CATALOG_CASES)
    return plan


def _updated_at(conn, plan_id: int) -> str:
    row = conn.execute(
        "SELECT updated_at FROM qa_plans WHERE id=%s", (plan_id,)
    ).fetchone()
    return str(row["updated_at"])


def _case_ids(conn, plan_id: int) -> list[int]:
    return [
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM qa_plan_cases WHERE plan_id=%s ORDER BY position",
            (plan_id,),
        ).fetchall()
    ]


def _edit(
    conn,
    plan: dict,
    *,
    base_updated_at: str,
    name: str = "Release readiness",
    description: str = "Initial contract.",
    cases: list[dict] | None = None,
    success_policy_id: str = "all-pass",
) -> dict:
    return edit_plan(
        conn,
        project="yoke",
        slug=plan["slug"],
        base_updated_at=base_updated_at,
        name=name,
        description=description,
        success_policy_id=success_policy_id,
        success_policy_params={},
        cases=cases or CATALOG_CASES,
    )
