# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from runtime.api.domain.deployment_qa_plan_group_execution_test_support import (
    OTHER,
    _begin,
    _fail_case,
    _settle,
)

from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    MEMBERS,
    RUN,
    SLUG,
    _attach,
    _pass_group,
    _seed,
)

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)

from yoke_core.domain.deployment_qa_plan_credit import plan_credit_misses

from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups

from yoke_core.domain.deployment_qa_plan_groups import run_groups

from yoke_core.domain.deployment_run_qa_transfer import transfer_qa_on

NEW = "run-plan-groups-taken-over"


def _take_over(conn, plan_id, *, late=()):
    """Seed a successor run holding every member, move QA and drop old membership."""
    stages = _stages(plan_id)
    stages[1].pop("cases")
    _seed_run(conn, run_id=NEW, stages=stages, members=late, existing_members=MEMBERS)
    conn.execute(
        "UPDATE deployment_runs SET supersedes_run_id=%s,created_at=%s WHERE id=%s",
        (RUN, "2026-09-15T00:00:00Z", NEW),
    )
    transfer_qa_on(conn, old_id=RUN, new_id=NEW, moving=set(MEMBERS))
    conn.execute("DELETE FROM deployment_run_items WHERE run_id=%s", (RUN,))
    conn.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=ANY(%s)",
        (f"flow-{NEW}", [*MEMBERS, *late]),
    )
    conn.commit()
