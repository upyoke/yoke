"""Parallel promotions retain their own deployed commit after trunk moves."""

import json
import pytest

from runtime.api.domain.coordination_claim_test_support import seed_project
from runtime.api.fixtures.release_output_source import git, insert_flow, insert_run
from runtime.api.fixtures.hosted_promotion import envelope, payload
from yoke_core.domain import deployment_qa_release_version as qa_version
from yoke_core.domain.deployment_run_project_sources import run_delivered_sha
from yoke_core.domain.deployment_run_release_output_record import (
    OUTCOME_ALREADY_RECORDED,
    OUTCOME_RECORDED,
    OUTCOME_NOTHING_PRODUCED,
    ReleaseOutputRefused,
    record_release_output,
)

pytest_plugins = ("runtime.api.fixtures.release_output_fixture",)


@pytest.mark.parametrize("order", [("prod", "stage"), ("stage", "prod")])
def test_interleaved_environment_outputs_and_qa_use_exact_deployed_commits(
    test_db,
    release_source,
    monkeypatch,
    order,
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
    (repo / "yoke-release-pin.txt").write_text(f"0.1.1+launch.{461}\n")
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
    site = test_db.execute(
        "INSERT INTO sites(project_id,name,created_at) VALUES (1,'parallel-carrier','2026-10-08T00:00:00Z') RETURNING id"
    ).fetchone()[0]
    for target, run_id in runs.items():
        env_id = test_db.execute(
            "INSERT INTO environments(site,project_id,name,created_at) VALUES (%s,1,%s,'2026-10-08T00:00:00Z') RETURNING id",
            (site, target),
        ).fetchone()[0]
        test_db.execute(
            "UPDATE deployment_runs SET target_tier='persistent',target_environment_id=%s WHERE id=%s",
            (env_id, run_id),
        )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_promotion_receipt.verify_promotion_provenance",
        lambda *a: None,
    )
    test_db.commit()

    # Each ordering records after main has moved. Previously Stage borrowed
    # main's production SHA rather than its own deployed environment pin.
    # Prod records first. Stage records only after main has moved past both
    # pins; the exact producer identity, rather than trunk, answers each call.
    for environment in order:
        deployed_sha = {"stage": stage_sha, "prod": prod_sha}[environment]
        proof = envelope(
            payload(
                product_sha=baseline,
                platform_sha=deployed_sha,
                proven_consumer_sha=baseline,
                target_environment=environment,
            )
        )
        receipt = record_release_output(
            test_db,
            run_id=runs[environment],
            project=project,
            commit_sha=deployed_sha,
            promotion_receipt=proof,
        )
        assert receipt["outcome"] == OUTCOME_RECORDED
        assert receipt["commit_sha"] == deployed_sha
        retry = record_release_output(
            test_db,
            run_id=runs[environment],
            project=project,
            commit_sha=deployed_sha,
            promotion_receipt=proof,
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
        ("stage", f"0.1.1+launch.{461}"),
        ("prod", f"0.1.1+launch.{459}"),
    ):
        target = qa_version.pinned_release_endpoints(
            test_db,
            runs[environment],
            project_id,
            {"installer_base_url": "https://install.example.test"},
        )
        assert target["release_version"] == version
    assert read_shas == [stage_sha, prod_sha]


@pytest.mark.parametrize("pushed", [True, False])
def test_validated_promotion_records_noop_and_retry_without_inventing_output(
    test_db,
    release_source,
    monkeypatch,
    pushed,
):
    from runtime.api.fixtures.hosted_promotion import envelope, payload
    from yoke_core.domain import deployment_run_promotion_receipt as promotions

    project_id = 995
    project = "promotion-consumer"
    seed_project(test_db, project_id, project)
    flow = "promotion-receipt-flow"
    insert_flow(test_db, flow)
    baseline = release_source["baseline"]
    deployed = release_source["pin"] if pushed else baseline
    run_id = "run-receipt"
    insert_run(
        test_db,
        run_id,
        baseline,
        flow_id=flow,
        status="executing",
        created_at="2026-10-08T00:00:00Z",
    )
    site = test_db.execute(
        "INSERT INTO sites(project_id,name,created_at) VALUES (1,'promotion-carrier','2026-10-08T00:00:00Z') RETURNING id"
    ).fetchone()[0]
    environment = test_db.execute(
        "INSERT INTO environments(site,project_id,name,created_at) VALUES (%s,1,'stage','2026-10-08T00:00:00Z') RETURNING id",
        (site,),
    ).fetchone()[0]
    test_db.execute(
        "UPDATE deployment_runs SET target_tier='persistent',target_environment_id=%s,bound_sources=%s WHERE id=%s",
        (
            environment,
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
                }
            ),
            run_id,
        ),
    )
    monkeypatch.setattr(promotions, "verify_promotion_provenance", lambda *a: None)
    proof = envelope(
        payload(
            product_sha=baseline,
            platform_sha=deployed,
            proven_consumer_sha=baseline,
            pin_pushed=pushed,
        )
    )
    result = record_release_output(
        test_db,
        run_id=run_id,
        project=project,
        commit_sha=deployed,
        promotion_receipt=proof,
    )
    assert result["outcome"] == (
        OUTCOME_RECORDED if pushed else OUTCOME_NOTHING_PRODUCED
    )
    assert run_delivered_sha(test_db, run_id, project_id) == deployed
    retry = record_release_output(
        test_db,
        run_id=run_id,
        project=project,
        commit_sha=deployed,
        promotion_receipt=proof,
    )
    assert retry["outcome"] == OUTCOME_ALREADY_RECORDED
    # A failed-job retry inherits the successful pin job output but publishes
    # current attempt provenance. It does not create another output commit.
    proof = envelope({**proof["payload"], "run_attempt": 2})
    record_release_output(
        test_db,
        run_id=run_id,
        project=project,
        commit_sha=deployed,
        promotion_receipt=proof,
    )
    raw = test_db.execute(
        "SELECT bound_sources FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()[0]
    sources = raw if isinstance(raw, dict) else json.loads(raw)
    entry = sources["projects"][0]
    assert len(entry["promotion_receipts"]) == 2
    assert len(entry.get("outputs", [])) == int(pushed)
    assert entry["promotion_receipts"][-1] == proof
    with pytest.raises(ReleaseOutputRefused) as stale:
        record_release_output(
            test_db,
            run_id=run_id,
            project=project,
            commit_sha=deployed,
            promotion_receipt=envelope({**proof["payload"], "run_attempt": 1}),
        )
    assert stale.value.reason == "promotion_attempt_stale"
    with pytest.raises(ReleaseOutputRefused) as ancestry:
        invalid = envelope(
            payload(
                product_sha=baseline,
                platform_sha="9" * 40,
                proven_consumer_sha=baseline,
            )
        )
        record_release_output(
            test_db,
            run_id=run_id,
            project=project,
            commit_sha="9" * 40,
            promotion_receipt=invalid,
        )

    assert ancestry.value.reason == "promotion_candidate_ancestry_unproven"
