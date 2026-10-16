"""Proof command scoping follows the current registered CLI response contract."""

import sqlite3

import pytest

from runtime.api.tools import materialization_deadline_proof as proof


@pytest.mark.parametrize(
    "count,returned_member", [(44, "EX-7"), (22, "EX-7"), (44, "EX-8")]
)
def test_member_project_and_public_ref_identity_are_required(
    monkeypatch, count, returned_member
):
    member, run, source = "EX-7", "run-current-proof", "a" * 40
    monkeypatch.setenv("DEPLOYMENT_RUN_ID", run)
    monkeypatch.setenv("DEPLOYMENT_MEMBER_REF", member)
    monkeypatch.setenv("YOKE_QA_CANDIDATE_TREE", '{"head_sha":"' + source + '"}')
    calls = []

    def call(*args):
        calls.append(args)
        if args[:2] == ("db", "read"):
            return {"rows": [[count, 1, member, "member-project"]]}, 0.1
        if args[:2] == ("deployment-runs", "get"):
            return {"value": "item-qa"}, 0.1
        if args[:3] == ("qa", "requirement", "list"):
            assert "--full" in args
            return {"rows": [{"id": 123}]}, 0.1
        assert args[:3] == ("qa", "plan", "materialize")
        assert args[args.index("--project") + 1] == "member-project"
        assert args[args.index("--member") + 1] == member
        return {
            "result": {
                "created_requirement_ids": [],
                "existing_requirement_ids": [123],
                "candidate_revision": source,
                "deployment_run_id": run,
                "deployment_stage": "item-qa",
                "deployment_member_public_ref": returned_member,
                "execution_target": {
                    "schema": 4,
                    "environment": {"name": "prod"},
                    "project": {"slug": "member-project"},
                    "deployment": {
                        "release_lineage": source,
                        "member_public_ref": returned_member,
                    },
                    "observation": {"observed_release_lineage": source},
                },
            }
        }, 0.1

    monkeypatch.setattr(proof, "call", call)
    if returned_member != member:
        with pytest.raises(RuntimeError, match="materialization_proof_member"):
            proof.main()
    else:
        proof.main()
        assert sum(args[:3] == ("qa", "plan", "materialize") for args in calls) == 2


def test_execution_count_ignores_other_members_stages_and_runs():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE deployment_run_items(run_id TEXT, item_id INTEGER);
        CREATE TABLE item_refs(item_id INTEGER, public_ref TEXT);
        CREATE TABLE items(id INTEGER, project_id INTEGER);
        CREATE TABLE projects(id INTEGER, slug TEXT);
        CREATE TABLE qa_plan_executions(
            deployment_run_id TEXT, deployment_stage TEXT,
            deployment_member_item_id INTEGER);
        INSERT INTO projects VALUES(1, 'member-project');
        INSERT INTO items VALUES(1,1),(2,1);
        INSERT INTO item_refs VALUES(1,'EX-7'),(2,'EX-8');
        INSERT INTO deployment_run_items VALUES('current',1),('current',2);
        INSERT INTO qa_plan_executions VALUES('current','item-qa',1);
    """)
    query = proof.population_query("current", "item-qa", "EX-7")
    before = conn.execute(query).fetchone()
    conn.executemany(
        "INSERT INTO qa_plan_executions VALUES(?,?,?)",
        [
            ("current", "item-qa", 2),
            ("current", "other-stage", 1),
            ("other-run", "item-qa", 1),
            ("current", "item-qa", None),
        ],
    )
    assert conn.execute(query).fetchone() == before == (2, 1, "EX-7", "member-project")
    conn.execute("INSERT INTO qa_plan_executions VALUES('current','item-qa',1)")
    assert conn.execute(query).fetchone() == (2, 2, "EX-7", "member-project")
