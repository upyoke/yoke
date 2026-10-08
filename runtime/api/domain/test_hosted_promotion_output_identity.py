"""Parallel promotions retain their own deployed commit after trunk moves."""

import json

from runtime.api.domain.coordination_claim_test_support import seed_project
from runtime.api.fixtures.release_output_source import git, insert_flow, insert_run
from yoke_core.domain import deployment_qa_release_version as qa_version
from yoke_core.domain.deployment_run_project_sources import run_delivered_sha
from yoke_core.domain.deployment_run_release_output_record import (
    OUTCOME_ALREADY_RECORDED,
    OUTCOME_RECORDED,
    record_release_output,
)

pytest_plugins = ("runtime.api.fixtures.release_output_fixture",)


def test_interleaved_environment_outputs_and_qa_use_exact_deployed_commits(
    test_db,
    release_source,
    monkeypatch,
):
    project_id = 995
    project = "promotion-consumer"
    seed_project(test_db, project_id, project)
    repo = release_source["repo"]
    baseline = release_source["baseline"]
    prod_sha = release_source["pin"]
    # Prod has already pushed a pin and unrelated main work has followed it.
    moving_main = release_source["maintenance"]
    git(repo, "checkout", "-b", "stage", baseline)
    (repo / "yoke-release-pin.txt").write_text("0.1.1+launch.461\n")
    git(repo, "add", "yoke-release-pin.txt")
    git(repo, "commit", "-m", "Pin Stage release")
    stage_sha = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "main")
    assert git(repo, "rev-parse", "HEAD") == moving_main
    assert len({stage_sha, prod_sha, moving_main}) == 3

    flow = "parallel-promotions"
    insert_flow(test_db, flow)
    test_db.execute(
        "UPDATE deployment_flows SET stages=%s WHERE id=%s",
        (
            json.dumps(
                [
                    {
                        "name": "complete",
                        "input_bindings": {
                            "consumer_sha": {"project": project, "branch": "main"},
                        },
                    }
                ]
            ),
            flow,
        ),
    )
    runs = {"stage": "run-promotion-stage", "prod": "run-promotion-prod"}
    for run_id in runs.values():
        insert_run(
            test_db,
            run_id,
            baseline,
            flow_id=flow,
            status="executing",
            created_at="2026-10-08T00:00:00Z",
        )
        test_db.execute(
            "UPDATE deployment_runs SET bound_sources=%s WHERE id=%s",
            (
                json.dumps(
                    {
                        "schema": 1,
                        "projects": [
                            {
                                "project": project,
                                "project_id": project_id,
                                "commit_sha": baseline,
                            }
                        ],
                        "inputs": {},
                    }
                ),
                run_id,
            ),
        )
    test_db.commit()

    # Prod records first. Stage records only after main has moved past both
    # pins; the exact producer identity, rather than trunk, answers each call.
    for environment, deployed_sha in (("prod", prod_sha), ("stage", stage_sha)):
        receipt = record_release_output(
            test_db,
            run_id=runs[environment],
            project=project,
            commit_sha=deployed_sha,
        )
        assert receipt["outcome"] == OUTCOME_RECORDED
        assert receipt["commit_sha"] == deployed_sha
        retry = record_release_output(
            test_db,
            run_id=runs[environment],
            project=project,
            commit_sha=deployed_sha,
        )
        assert retry["outcome"] == OUTCOME_ALREADY_RECORDED
        assert run_delivered_sha(test_db, runs[environment], project_id) == deployed_sha

    monkeypatch.setattr(qa_version, "_pin_file", lambda *a: "yoke-release-pin.txt")
    read_shas = []

    def read_pin(_conn, _project_id, sha, path):
        read_shas.append(sha)
        return git(repo, "show", f"{sha}:{path}").encode()

    monkeypatch.setattr(qa_version, "read_project_file", read_pin)
    monkeypatch.setattr(qa_version, "require_published", lambda *a: None)
    for environment, version in (
        ("stage", "0.1.1+launch.461"),
        ("prod", "0.1.1+launch.459"),
    ):
        target = qa_version.pinned_release_endpoints(
            test_db,
            runs[environment],
            project_id,
            {"installer_base_url": "https://install.example.test"},
        )
        assert target["release_version"] == version
    assert read_shas == [stage_sha, prod_sha]
