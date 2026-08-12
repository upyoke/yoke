"""Host-baseline proof-union contract tests for QA plan detail."""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_catalog_test_support import CATALOG_CASES
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)


def test_plan_detail_requires_every_case_baseline_proof_to_satisfy_union() -> None:
    with test_database() as conn:
        insert_item(conn, id=42, title="Prove installation", workflow_id="issue")
        plan = create_plan(
            conn,
            project="yoke",
            slug="installer-proof",
            name="Installer proof",
        )
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=[
                {
                    **CATALOG_CASES[0],
                    "case_key": "cold-start-hosted",
                    "host_baselines": ["fresh-host", "shell-preconfigured"],
                },
                {
                    **CATALOG_CASES[0],
                    "case_key": "backend-suite",
                    "position": 2,
                },
            ],
        )
        set_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id="issue",
            transition_id="release",
        )
        materialize_for_item(conn, item_id=42, transition_id="release")
        requirements = conn.execute(
            "SELECT id, plan_case_key, host_baseline FROM qa_requirements "
            "WHERE plan_id=%s ORDER BY id",
            (plan["id"],),
        ).fetchall()
        by_proof = {
            (str(row["plan_case_key"]), row["host_baseline"]): int(row["id"])
            for row in requirements
        }
        run_specs = [
            (
                by_proof[("cold-start-hosted", "fresh-host")],
                "fail",
                "failed",
                "2026-07-26T12:00:00Z",
                "fresh-host.txt",
            ),
            (
                by_proof[("cold-start-hosted", "shell-preconfigured")],
                "pass",
                "passed",
                "2026-07-26T13:00:00Z",
                "shell-preconfigured.txt",
            ),
            (
                by_proof[("backend-suite", None)],
                "pass",
                "passed",
                "2026-07-26T14:00:00Z",
                "backend-suite.txt",
            ),
        ]
        artifact_ids = {}
        for requirement_id, verdict, outcome, happened_at, filename in run_specs:
            run = conn.execute(
                "INSERT INTO qa_runs("
                "qa_requirement_id, performed_by, qa_kind, verdict, "
                "case_outcome, created_at"
                ") VALUES (%s, 'worktree_run', 'command', %s, %s, %s) "
                "RETURNING id",
                (requirement_id, verdict, outcome, happened_at),
            ).fetchone()
            artifact = conn.execute(
                "INSERT INTO qa_artifacts("
                "qa_run_id, artifact_type, content_type, artifact_handle, "
                "created_at"
                ") VALUES (%s, 'command_output', 'text/plain', %s, %s) "
                "RETURNING id",
                (
                    run["id"],
                    json.dumps({"backend": "local", "path": filename}),
                    happened_at,
                ),
            ).fetchone()
            artifact_ids[filename] = int(artifact["id"])
        conn.commit()
        detail = get_plan(conn, plan_id=plan["id"])

    baseline_case = detail["cases"][0]
    assert "last_result" not in baseline_case
    assert [proof["host_baseline"] for proof in baseline_case["proofs"]] == [
        "fresh-host",
        "shell-preconfigured",
    ]
    assert [proof["outcome"] for proof in baseline_case["proofs"]] == [
        "failed",
        "passed",
    ]
    assert [proof["evidence"][0]["id"] for proof in baseline_case["proofs"]] == [
        artifact_ids["fresh-host.txt"],
        artifact_ids["shell-preconfigured.txt"],
    ]
    plain_case = detail["cases"][1]
    assert len(plain_case["proofs"]) == 1
    assert plain_case["proofs"][0] == plain_case["last_result"]
    assert plain_case["last_result"]["host_baseline"] is None
    assert detail["union"] == {
        "satisfied": False,
        "counts": {"failed": 1, "passed": 2},
    }
