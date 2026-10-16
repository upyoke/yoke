"""Load private reviewed run captures only into the disposable test database."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from psycopg import sql

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource
from yoke_core.domain import qa_plan_source_revision

PROOF_DIR = os.environ.get("YOKE_QA_SNAPSHOT_PROOF_DIR")
NOW = "2026-10-15T00:00:00Z"


def read_capture(name):
    return json.loads((Path(PROOF_DIR) / name).read_text())


def capture_rows(name):
    document = read_capture(name)
    if "result" in document:
        document = document["result"]
    assert not document["truncated"]
    assert document["row_count"] == len(document["rows"])
    return [
        dict(zip(document["columns"], row, strict=True)) for row in document["rows"]
    ]


def _insert(conn, table, row, *, omit=()):
    row = {key: value for key, value in row.items() if key not in omit}
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) {} VALUES ({}) ON CONFLICT DO NOTHING").format(
            sql.Identifier(table),
            sql.SQL(",").join(map(sql.Identifier, row)),
            sql.SQL("OVERRIDING SYSTEM VALUE" if table == "qa_plan_executions" else ""),
            sql.SQL(",").join(sql.Placeholder() for _ in row),
        ),
        tuple(
            json.dumps(value) if isinstance(value, (dict, list)) else value
            for value in row.values()
        ),
    )


def digest_rows(conn, table):
    rows = conn.execute(
        sql.SQL("SELECT row_to_json(t)::text FROM {} t ORDER BY 1").format(
            sql.Identifier(table)
        )
    ).fetchall()
    return hashlib.sha256(json.dumps([row[0] for row in rows]).encode()).hexdigest()


@pytest.fixture
def preserved(test_db, monkeypatch):
    conn = test_db
    members = capture_rows("proof-members.json")
    requirements = [
        *capture_rows("requirements-current.json"),
        *capture_rows("requirements-settling.json"),
        *capture_rows("source-requirements-full.json"),
    ]
    before = capture_rows("member-before.json")
    images = read_capture("review-document.json")
    after = {
        (row["run_id"], row["public_ref"]): row["requirement_snapshot"]
        for row in images["after"]
    }
    mapping = {
        (row["run_id"], f"{row['public_item_prefix']}-{row['project_sequence']}"): row
        for row in members
    }
    for project in capture_rows("bridge-projects.json"):
        _insert(conn, "projects", {**project, "created_at": NOW})
        conn.execute(
            "UPDATE projects SET slug=%s,name=%s,org_id=%s WHERE id=%s",
            (project["slug"], project["name"], project["org_id"], project["id"]),
        )
    tenant = json.loads(
        next(
            row["execution_target_json"]
            for row in requirements
            if row["execution_target_json"]
        )
    )["tenant"]
    conn.execute(
        "UPDATE organizations SET slug=%s,name=%s WHERE id=%s",
        (tenant["slug"], tenant["name"], tenant["id"]),
    )
    # Seed identities may occupy production IDs; retain target IDs while
    # keeping unrelated fixture site owners separate.
    conn.execute("UPDATE environments SET name='fixture-' || id")
    for environment in capture_rows("hosted-bridge-environments.json"):
        if environment["project_id"] != 1:
            environment["site"] += 10000
        owner = environment["project_id"]
        site = "Yoke API" if owner != 1 else "yoke"
        _insert(
            conn,
            "sites",
            {
                "id": environment["site"],
                "project_id": owner,
                "name": site,
                "created_at": NOW,
            },
        )
        conn.execute(
            "UPDATE sites SET name=%s,project_id=%s WHERE id=%s",
            (site, owner, environment["site"]),
        )
        qa = environment.pop("qa")
        environment["settings"] = {"qa": json.loads(qa) if isinstance(qa, str) else qa}
        conn.execute("DELETE FROM environments WHERE id=%s", (environment["id"],))
        _insert(conn, "environments", environment)
    ids = {row["item_id"] for row in members} | {
        row["item_id"] for row in requirements if row["item_id"] is not None
    }
    owners = {row["item_id"]: row["project_id"] for row in members}
    identities = {row["item_id"]: row for row in members}
    for item_id in sorted(ids):
        insert_item(
            conn,
            id=item_id,
            project_id=owners.get(item_id, 1),
            project_sequence=identities.get(item_id, {}).get(
                "project_sequence", item_id
            ),
            workflow_id="issue",
            status=identities.get(item_id, {}).get("status", "release"),
        )
    plans = {}
    for row in images["after"]:
        for snapshot in json.loads(row["requirement_snapshot"])["plans"]:
            plans[int(snapshot["plan"]["id"])] = snapshot
    for plan in capture_rows("current-plan-membership-state.json"):
        _insert(conn, "qa_plans", plan)
    for snapshot in plans.values():
        for case in snapshot["cases"]:
            _insert(
                conn,
                "qa_methods",
                {
                    "id": case["method_id"],
                    "name": case["method_name"],
                    "description": "Preserved method",
                    "source_kind": "project",
                    "project_id": 1,
                    "runner_id": case["runner_id"],
                    "verdict_path": case["verdict_path"],
                    "verdict_contract": "preserved",
                    "evidence_contract": "preserved",
                    "config_contract_id": case["config_contract_id"],
                    "created_at": NOW,
                    "updated_at": NOW,
                },
            )
    flow = capture_rows("original-flow-definition.json")[0]
    pending = {row["id"]: row for row in capture_rows("parent-flow-definition.json")}
    while pending:
        ready = [
            row for row in pending.values() if row["supersedes_flow_id"] not in pending
        ]
        assert ready, "captured predecessor chain contains a cycle"
        for parent in ready:
            _insert(conn, "deployment_flows", parent)
            del pending[parent["id"]]
    _insert(conn, "deployment_flows", flow)
    for row in capture_rows("run-protected-before.json"):
        _insert(
            conn,
            "deployment_runs",
            {
                **row,
                "flow": flow["id"],
                "target_tier": "persistent",
                "target_environment_id": flow["target_environment_id"],
                "created_at": NOW,
            },
        )
    for row in before:
        member = mapping[(row["run_id"], row["public_ref"])]
        _insert(
            conn,
            "deployment_run_items",
            {
                "run_id": row["run_id"],
                "item_id": member["item_id"],
                "added_at": NOW,
                "requirement_selection": row["requirement_selection"],
                "requirement_snapshot": after.get(
                    (row["run_id"], row["public_ref"]), row["requirement_snapshot"]
                ),
            },
        )
    for row in capture_rows("stage-receipts.json"):
        _insert(conn, "deployment_stage_receipts", row)
    for row in requirements:
        _insert(
            conn,
            "qa_requirements",
            row,
            omit=("replacement_requirement_id", "superseded_by_requirement_id"),
        )
    for row in requirements:
        conn.execute(
            "UPDATE qa_requirements SET replacement_requirement_id=%s,superseded_by_requirement_id=%s WHERE id=%s",
            (
                row["replacement_requirement_id"],
                row["superseded_by_requirement_id"],
                row["id"],
            ),
        )
    for row in capture_rows("all-member-attachments.json"):
        _insert(conn, "qa_plan_item_attachments", row)
    for row in sorted(
        capture_rows("executions-full.json"), key=lambda row: row["execution_order"]
    ):
        _insert(conn, "qa_plan_executions", row)
    for name, table in [
        ("qa-results-full.json", "qa_runs"),
        ("artifact-receipts-full.json", "qa_artifacts"),
        ("execution-results.json", "qa_plan_execution_results"),
        ("review-bundles-full.json", "qa_plan_review_bundles"),
        ("review-verdicts.json", "qa_plan_review_verdicts"),
    ]:
        for row in capture_rows(name):
            _insert(conn, table, row)
    conn.commit()
    source_root = Path(__file__).resolve().parents[3]
    monkeypatch.setattr(
        qa_plan_source_revision,
        "open_carried_work_source",
        lambda conn, project_id: LocalCheckoutSource(str(source_root)),
    )
    return conn, members, images, requirements
