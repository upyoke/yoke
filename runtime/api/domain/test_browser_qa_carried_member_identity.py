"""A carried member's QA is judged against the build its own project serves.

A run can carry members of a bound project. That project's target serves its
own build -- the release output the run recorded for it (a version pin it
materialized onto the project's trunk), or the commit it bound when it
produced none -- never the carrying run's lineage. Comparing against the
carrier's lineage refused a target serving exactly what the run deployed.
"""

from __future__ import annotations

import json

from ops.qa.mission_preparation_evidence import _delivered_commits
from yoke_core.domain.browser_qa_deployment_identity import (
    DeploymentUnderTest,
    resolve_run_pinned_source,
)
from yoke_core.domain.browser_qa_freshness import _establish_deployment_freshness
from yoke_core.domain.deployment_run_project_sources import delivered_source_sha
from yoke_core.domain.qa_review_requirement_facts import frozen_target_facts
from yoke_core.domain.served_revision_probe import ServedRevisionRead

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database

RUN_ID = "run-carried-member"
LINEAGE = "a" * 40
BOUND = "b" * 40
OUTPUT = "c" * 40
OTHER = "d" * 40
BOUND_PROJECT_ID = 2


def _bound_sources(*, with_output: bool) -> str:
    entry = {"project_id": BOUND_PROJECT_ID, "commit_sha": BOUND}
    if with_output:
        entry["outputs"] = [
            {"commit_sha": OUTPUT, "reason": "release_pin_materialization"}
        ]
    return json.dumps({"schema": 1, "projects": [entry]})


def _run(*, with_output: bool = True) -> dict:
    return {
        "project_id": 1,
        "release_lineage": LINEAGE,
        "bound_sources": _bound_sources(with_output=with_output),
    }


def test_the_run_project_delivers_its_lineage() -> None:
    assert delivered_source_sha(_run(), 1) == LINEAGE


def test_a_bound_project_delivers_its_recorded_release_output() -> None:
    assert delivered_source_sha(_run(), BOUND_PROJECT_ID) == OUTPUT


def test_a_bound_project_without_output_delivers_its_bound_commit() -> None:
    assert delivered_source_sha(_run(with_output=False), BOUND_PROJECT_ID) == BOUND


def _seed(conn, *, with_output: bool = True) -> dict[str, int]:
    insert_deployment_run(
        conn,
        id=RUN_ID,
        status="executing",
        release_lineage=LINEAGE,
        bound_sources=_bound_sources(with_output=with_output),
    )
    insert_item(conn, id=9901, project="externalwebapp", project_sequence=9901)
    insert_item(conn, id=9902, project="yoke", project_sequence=9902)
    ids = {}
    for member in (9901, 9902):
        row = insert_qa_requirement(
            conn,
            item_id=None,
            deployment_run_id=RUN_ID,
            deployment_stage="item-qa",
            deployment_member_item_id=member,
            qa_kind="method_case",
            qa_phase="post_deploy",
            method_id="browser-check",
            method_name="Browser",
        )
        ids[str(member)] = int(row["id"])
    conn.commit()
    return ids


def test_a_carried_member_case_expects_its_project_release_output() -> None:
    with test_database() as conn:
        ids = _seed(conn)
        source = resolve_run_pinned_source(conn, RUN_ID, requirement_id=ids["9901"])
    assert source["sha"] == OUTPUT
    assert source["project"] == "externalwebapp"


def test_a_carried_member_without_output_expects_its_bound_commit() -> None:
    with test_database() as conn:
        ids = _seed(conn, with_output=False)
        source = resolve_run_pinned_source(conn, RUN_ID, requirement_id=ids["9901"])
    assert source["sha"] == BOUND


def test_a_same_project_member_case_expects_the_run_lineage() -> None:
    with test_database() as conn:
        ids = _seed(conn)
        source = resolve_run_pinned_source(conn, RUN_ID, requirement_id=ids["9902"])
    assert source["sha"] == LINEAGE
    assert source["project"] == "yoke"


def _freshness(served: str):
    target = DeploymentUnderTest(
        environment="prod", origin="https://app.example.test", identity_path="/b"
    )
    return _establish_deployment_freshness(
        "externalwebapp",
        "main",
        OUTPUT,
        context={
            "deployment_target": target.as_payload(),
            "run_source": {"sha": OUTPUT, "project": "externalwebapp"},
        },
        fetch_identity=lambda url: ServedRevisionRead(status=200, body=served),
    )


def test_a_target_serving_the_release_output_is_fresh() -> None:
    failure, origin, sha = _freshness(OUTPUT)
    assert failure is None
    assert (origin, sha) == ("https://app.example.test", OUTPUT)


def test_a_genuinely_different_served_commit_still_refuses_by_name() -> None:
    failure, _origin, _sha = _freshness(OTHER)
    assert failure is not None
    assert failure.reason == "sha_mismatch"
    assert OTHER in failure.message and OUTPUT in failure.message
    assert "project 'externalwebapp'" in failure.message


def _frozen(project_id: int) -> str:
    return json.dumps(
        {
            "project": {"id": project_id},
            "deployment": {"run_id": RUN_ID, "release_lineage": LINEAGE},
        }
    )


def test_a_carried_member_requirement_names_its_project_candidate() -> None:
    with test_database() as conn:
        _seed(conn)
        carried = frozen_target_facts(conn, _frozen(BOUND_PROJECT_ID))
        own = frozen_target_facts(conn, _frozen(1))
    assert carried["execution_candidate_revision"] == OUTPUT
    assert own["execution_candidate_revision"] == LINEAGE


def test_mission_evidence_accepts_every_commit_the_run_delivered() -> None:
    run = {
        "release_lineage": LINEAGE,
        "bound_sources": _bound_sources(with_output=True),
    }
    assert _delivered_commits(run) == {LINEAGE, OUTPUT}
