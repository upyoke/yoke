"""A deployment QA case names the commit its run shipped for the case's project.

A run carries one commit per project: its own lineage, and the source it bound
for each other project. A member from a bound project is checked out in that
project's repository, so the case contract must name that project's commit --
comparing its checkout with the carrier's lineage refused a checkout that sat
exactly where the run shipped it.
"""

from __future__ import annotations

import json

from runtime.api.domain.test_deployment_qa_stage_execution import _seed_run
from runtime.api.domain.test_direct_deployment_qa_case_execution import _qa_stages
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from yoke_core.domain.qa_case_execution_context import get_case_execution_context


def test_a_bound_project_member_case_names_its_bound_source(test_db) -> None:
    """A member from a project the run binds answers to that project's commit."""
    bound_sha = "e" * 40
    insert_item(
        test_db,
        id=9813,
        project="externalwebapp",
        project_sequence=9813,
        workflow_id="dash",
        status="release",
    )
    _seed_run(
        test_db,
        run_id="run-direct-bound",
        stages=_qa_stages(),
        members=(),
        existing_members=(9813,),
    )
    site_id = test_db.execute(
        "INSERT INTO sites(project_id,name,created_at) "
        "VALUES (2,'member-destination','2026-09-14T00:00:00Z') RETURNING id"
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO environments(site,project_id,name,url,created_at) "
        "VALUES (%s,2,'stage','https://preview.example.test','2026-09-14T00:00:00Z')",
        (site_id,),
    )
    test_db.execute(
        "UPDATE deployment_runs SET bound_sources=%s WHERE id='run-direct-bound'",
        (json.dumps({"projects": [{"project_id": 2, "commit_sha": bound_sha}]}),),
    )
    test_db.commit()
    row = insert_qa_requirement(
        test_db,
        item_id=None,
        deployment_run_id="run-direct-bound",
        deployment_stage="item-qa",
        deployment_member_item_id=9813,
        qa_kind="method_case",
        qa_phase="post_deploy",
        method_id="command",
        method_name="Command",
        runner_id="worktree_run",
        verdict_path="automatic",
        capability_requirements="[]",
        instructions="run the member smoke command",
        expected_outcome="the command passes",
        method_config=json.dumps({"command": "true"}),
        target_env="stage",
    )

    context = get_case_execution_context(test_db, requirement_id=int(row["id"]))

    assert context["project"] == "externalwebapp"
    assert context["deployment_source_revision"] == bound_sha
