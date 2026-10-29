"""Delete unused post-deploy plan copies now that plan groups answer plans.

Older builds copied each post-deploy plan's cases onto every attaching item
and admitted those copies into each release. Plan groups replace them: a
release runs each attached plan once, and the done gate credits items from
``qa_requirements.covered_item_ids`` (boot adds the column). A copy that any
run, execution result, review verdict or correction link references stays as
history; the rest are deleted. No release reads a copy once apply has proved
no unfinished release was composed with them, so the invariant holds for good.

The release carrying plan groups must not adopt an unfinished release that
older builds already materialized with plan copies or old shared rows.
Snapshot plans alone are harmless: item QA forms groups from live attachments. Apply refuses by name while one exists, so preflight refuses the
release instead of a run breaking mid-stage. The serving floor drains older
builds, whose done gate would pass an item whose copies are gone.
"""

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE

UNFINISHED = "('created','executing')"

COPY = (
    "q.item_id IS NOT NULL AND q.plan_id IS NOT NULL "
    "AND q.qa_phase='post_deploy' AND q.deployment_run_id IS NULL"
)

UNREFERENCED = (
    "NOT EXISTS (SELECT 1 FROM qa_runs r WHERE r.qa_requirement_id=q.id) "
    "AND NOT EXISTS (SELECT 1 FROM qa_plan_execution_results e WHERE e.requirement_id=q.id) "
    "AND NOT EXISTS (SELECT 1 FROM qa_plan_review_verdicts v WHERE v.requirement_id=q.id) "
    "AND NOT EXISTS (SELECT 1 FROM qa_requirements o WHERE o.superseded_by_requirement_id=q.id "
    "OR o.replacement_requirement_id=q.id) "
    "AND q.superseded_by_requirement_id IS NULL AND q.replacement_requirement_id IS NULL"
)

OLD_MODEL_RUNS = (
    "SELECT DISTINCT d.id FROM deployment_runs d WHERE d.status IN "
    f"{UNFINISHED} AND (EXISTS (SELECT 1 FROM deployment_run_items m WHERE m.run_id=d.id "
    "AND jsonb_array_length(COALESCE(NULLIF(m.requirement_snapshot,'')::jsonb->'plans',"
    "'[]'::jsonb))>0 AND EXISTS (SELECT 1 FROM qa_requirements q WHERE "
    "q.deployment_run_id=d.id AND q.deployment_member_item_id=m.item_id "
    "AND q.plan_id IN (SELECT (p->'plan'->>'id')::bigint FROM jsonb_array_elements("
    "NULLIF(m.requirement_snapshot,'')::jsonb->'plans') p))) "
    "OR EXISTS (SELECT 1 FROM qa_requirements s WHERE "
    "s.deployment_run_id=d.id AND s.deployment_member_item_id IS NULL AND s.plan_id IS NOT NULL "
    "AND jsonb_typeof(NULLIF(s.execution_target_json,'')::jsonb->'deployment'->'shared_plan')"
    "='object' AND NOT jsonb_exists(NULLIF(s.execution_target_json,'')::jsonb->'deployment'"
    "->'shared_plan','group_id'))) ORDER BY d.id"
)

TABLES = (
    "qa_requirements",
    "qa_runs",
    "qa_plan_execution_results",
    "qa_plan_review_verdicts",
    "deployment_runs",
    "deployment_run_items",
)


def _old_model_runs(conn: Any) -> list[str]:
    return [str(row[0]) for row in conn.execute(OLD_MODEL_RUNS).fetchall()]


def apply(conn: Any) -> None:
    if not all(_table_exists(conn, table) for table in TABLES):
        return
    blocking = _old_model_runs(conn)
    if blocking:
        raise RuntimeError(
            "old_model_plan_runs_unfinished: unfinished release(s) "
            f"{', '.join(blocking)} were composed with post-deploy plan copies, "
            "which this build no longer reads. Finish or cancel each with the "
            "build that started it (`yoke deployment-runs get RUN`, then drive it "
            "to done or cancel it), then rerun preflight for this release."
        )
    conn.execute(f"DELETE FROM qa_requirements q WHERE {COPY} AND {UNREFERENCED}")


def invariants(conn: Any) -> None:
    if not all(_table_exists(conn, table) for table in TABLES):
        return
    row = conn.execute(
        f"SELECT COUNT(*) FROM qa_requirements q WHERE {COPY} AND {UNREFERENCED}"
    ).fetchone()
    assert int(row[0]) == 0, (
        f"post_deploy_item_qa_copies_remain: {row[0]} unreferenced post-deploy plan "
        "copies; boot must apply migration 0094"
    )
