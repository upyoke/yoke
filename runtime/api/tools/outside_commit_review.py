"""Seed outside-commit presentation fixtures in the disposable render universe.

Run with `yoke dev run -- env YOKE_ENV=render-proof python3 -m
runtime.api.tools.outside_commit_review`, then serve_workbench_for_review on
that same connection. These are presentation fixtures, never deployment runs
to execute. The real list readers and all real UI views read this stored work.
"""

import json

from runtime.api.tools.serve_workbench_for_review import prepare_review_database
from yoke_core.domain.db_helpers import connect
from yoke_core.ui.served_universe_connection import serving_connection


def main() -> None:
    environment, refusal = serving_connection()
    if environment != "render-proof" or refusal:
        raise SystemExit(
            "outside_commit_review_requires_render_proof: select the disposable "
            "render-proof connection with YOKE_ENV=render-proof, then retry"
        )
    prepare_review_database()
    first, second = "a" * 40, "b" * 40
    carried = {
        "schema": 3,
        "derivation": {
            "contents_known": True,
            "status": "derived",
            "reason": "complete",
        },
        "items": [],
        "commits": [first],
        "commit_subjects": {first: "Fix navigation after a direct hotfix"},
        "commit_authors": {first: "A maintainer"},
        "bound_projects": [
            {
                "project": "sample-api",
                "project_id": 2,
                "items": [],
                "commits": [second],
                "commit_subjects": {second: "Install Yoke operating layer"},
                "commit_authors": {second: "Automation"},
                "derivation": {
                    "contents_known": True,
                    "status": "derived",
                    "reason": "complete",
                },
            }
        ],
    }
    with connect() as conn:
        project = conn.execute("SELECT id FROM projects WHERE slug='yoke'").fetchone()
        if project is None:
            raise SystemExit(
                "outside_commit_review_project_missing: seed the review universe's yoke project first"
            )
        project_id = int(project[0])
        conn.execute(
            "INSERT INTO deployment_flows(id,project_id,name,description,stages,created_at,status,takes_delivery_custody) "
            "VALUES ('outside-commit-review',%s,'Outside commits review','Presentation fixture',"
            "'[{\"name\":\"deploy\"}]',now(),'disabled',0) ON CONFLICT(id) DO NOTHING",
            (project_id,),
        )
        conn.execute(
            "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,current_stage,"
            "created_at,started_at,carried_work,created_by) VALUES "
            "('run-outside-commit-review',%s,'outside-commit-review',%s,'executing','deploy',"
            "now(),now(),%s,'presentation fixture') ON CONFLICT(id) DO UPDATE "
            "SET carried_work=excluded.carried_work,created_at=excluded.created_at",
            (project_id, first, json.dumps(carried)),
        )
    print("review fixture: run-outside-commit-review (render-proof only)")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(
            f"outside_commit_review_seed_failed: {exc}; repair the render-proof "
            "fixture data and retry seeding before starting the review server"
        ) from None
