"""Read durable proof of private QA completing before its shared campaign."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys


def main() -> int:
    run_id = os.environ.get("DEPLOYMENT_RUN_ID", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        print(
            "PRIVATE-QA-SUBJECT: run this case through its admitted deployment member"
        )
        return 1
    # Diagnostic SQL goes through the registered read surface. This probe
    # observes an actual admitted mixed member without acquiring a cursor,
    # starting a campaign, or depending on that campaign's eventual verdict.
    sql = f"""
        SELECT DISTINCT e.id AS private_execution_id, e.deployment_stage,
               e.deployment_member_item_id, q.execution_target_digest AS shared_target
        FROM qa_plan_executions e
        JOIN deployment_run_items m ON m.run_id=e.deployment_run_id
            AND m.item_id=e.deployment_member_item_id
        JOIN qa_requirements q ON q.deployment_run_id=e.deployment_run_id
            AND q.deployment_stage=e.deployment_stage
            AND q.deployment_member_item_id IS NULL
        WHERE e.deployment_run_id='{run_id}' AND e.state='completed'
            AND e.deployment_member_item_id IS NOT NULL
            AND q.method_id IS NOT NULL AND q.waived_at IS NULL
            AND q.retracted_at IS NULL AND q.replacement_requirement_id IS NULL
            AND q.superseded_by_requirement_id IS NULL
            AND q.execution_target_json::jsonb #> '{{deployment,shared_plan}}' IS NOT NULL
            AND (e.execution_target_json::jsonb #- '{{deployment,member_item_id}}')
                = (q.execution_target_json::jsonb #- '{{deployment,shared_plan}}')
            AND (
                EXISTS (SELECT 1 FROM qa_plan_item_attachments a
                    WHERE a.item_id=m.item_id AND a.plan_id=q.plan_id
                        AND a.qa_phase='post_deploy')
                OR
                EXISTS (SELECT 1 FROM jsonb_array_elements(
                    m.requirement_snapshot::jsonb->'requirements') r
                    WHERE (r->>'plan_id')::bigint=q.plan_id
                        AND r->>'qa_phase'='post_deploy')
                OR EXISTS (SELECT 1 FROM jsonb_array_elements(
                    m.requirement_snapshot::jsonb->'plans') p
                    WHERE (p #>> '{{plan,id}}')::bigint=q.plan_id
                        AND p #>> '{{attachment,qa_phase}}'='post_deploy')
            )
            AND jsonb_array_length(e.roster_json::jsonb)>0
            AND (SELECT COUNT(*) FROM qa_plan_execution_results r
                WHERE r.execution_id=e.id)
                = jsonb_array_length(e.roster_json::jsonb)
            AND NOT EXISTS (SELECT 1 FROM qa_plan_execution_results r
                WHERE r.execution_id=e.id
                    AND COALESCE(r.result_json::jsonb->>'verdict','')<>'pass')
            AND NOT EXISTS (SELECT 1 FROM qa_plan_executions s
                WHERE s.deployment_run_id=e.deployment_run_id
                    AND s.deployment_stage=e.deployment_stage
                    AND s.execution_target_digest=q.execution_target_digest
                    AND s.state='completed' AND s.completed_at<=e.completed_at)
        ORDER BY e.id LIMIT 1
    """
    result = subprocess.run(
        ["yoke", "db", "read", sql, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    try:
        response = json.loads(result.stdout)
        if result.returncode or not response.get("success"):
            raise ValueError(str(response.get("error") or "registered read failed"))
        proof = response["result"]
        if proof.get("truncated") or not proof["rows"]:
            raise ValueError(
                "no completed private roster before its admitted shared group"
            )
    except (ValueError, KeyError) as exc:
        print(
            f"PRIVATE-QA-PROOF-MISSING: {exc}. Recovery: have the mixed member's "
            "owner run its scoped private QA on this deployed candidate, retain its "
            "execution receipt, then rerun this case. Keep shared host readiness "
            "and campaign ownership intact; this probe never starts that campaign."
        )
        return 1
    print(json.dumps({"run_id": run_id, "proof": proof}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
