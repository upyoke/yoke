"""Resolve observation windows from durable member delivery across release takeovers."""

from __future__ import annotations


def first_deployment_sql(quoted_run: str, requirement_selector: str) -> str:
    """Keep the clock through takeovers; selector is caller-owned SQL on alias q."""
    return (
        "(SELECT MIN(delivered_at) FROM (SELECT MAX(r.completed_at) AS delivered_at "
        "FROM deployment_stage_receipts r JOIN deployment_runs d ON d.id=r.run_id "
        "WHERE r.status='ready' AND d.target_environment_id="
        f"(SELECT target_environment_id FROM deployment_runs WHERE id={quoted_run}) "
        "AND EXISTS (SELECT 1 FROM qa_requirements q "
        f"WHERE q.deployment_run_id={quoted_run} AND ({requirement_selector}) "
        "AND (EXISTS (SELECT 1 FROM deployment_run_items di WHERE di.run_id=d.id "
        "AND di.item_id=q.deployment_member_item_id) OR EXISTS (SELECT 1 FROM "
        "jsonb_array_elements(COALESCE(d.membership_removals,'[]')::jsonb) removed "
        "WHERE (removed->>'item_id')::bigint=q.deployment_member_item_id "
        "AND removed->>'transferred_to_run_id' IS NOT NULL))) "
        "GROUP BY r.run_id) delivered)"
    )

