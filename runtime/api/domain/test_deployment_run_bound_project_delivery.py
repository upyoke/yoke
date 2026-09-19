"""A release that ships two projects credits the items in both of them.

A flow stage may bind another registered project's branch, and the build it
dispatches ships that project's code. These tests drive the real resolution,
the real commit comparison and the real membership writes across two actual
repositories, because the whole point of the record is that the commit a run
shipped and the commit it is later judged on are the same one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_insert_support import ensure_project_id
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    bound_source_repository,
    git,
    insert_run,
    item_ref,
    serve_repositories,
    stage_environment,
)
from yoke_core.domain.deployment_run_bound_sources import (
    declared_bindings,
    parse_bound_sources,
    record_bound_sources,
)
from yoke_core.domain.deployment_run_carried_membership import (
    carried_membership_refusal,
    enroll_carried_members,
)
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_project_sources import (
    carried_project_ids,
    run_source_sha,
)
from yoke_core.domain.delivery_evidence_ladder import DISCHARGED, delivery_evidence
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.workflow_delivery_binding_validation import (
    validate_deployment_run_item,
)
from yoke_core.domain.workflow_item_binding_validation import (
    WorkflowItemBindingError,
)


CARRIER_FLOW = "carrier-release-flow"
CONSUMER_FLOW = "consumer-release-flow"
CONSUMER_PROJECT = "consumer"
CARRIER_ITEM_ID = 9601
CONSUMER_ITEM_ID = 9602
UNBOUND_ITEM_ID = 9603
UNBOUND_PROJECT = "bystander"


def _stages(*, project: str = CONSUMER_PROJECT, branch: str = "main") -> str:
    return json.dumps(
        [
            {
                "name": "hosted-release",
                "step_runner": "github-actions-workflow",
                "workflow": "release.yml",
                "stage_kind": "execution",
                "scope": "run",
                "input_bindings": {
                    "consumer_sha": {"project": project, "branch": branch}
                },
                "inputs": {"consumer_sha": "{consumer_sha}"},
            }
        ]
    )


def _plain_stages() -> str:
    return json.dumps(
        [
            {
                "name": "stage",
                "step_runner": "auto",
                "stage_kind": "execution",
                "scope": "run",
            }
        ]
    )


def _project_id(conn: Any, slug: str) -> int:
    row = conn.execute(
        "SELECT id FROM projects WHERE slug=%s", (slug,)
    ).fetchone()
    return int(row[0])


def _two_project_release(
    conn: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    consumer_status: str = "implementing",
    stages: str | None = None,
) -> dict[str, Any]:
    """A carrier run whose flow binds a consumer project's trunk."""
    stage_environment(conn)
    ensure_project_id(conn, CONSUMER_PROJECT, ts="2026-09-14T00:00:00Z")
    conn.commit()
    cmd_create(
        conn, CARRIER_FLOW, "yoke", "Carrier", "",
        stages if stages is not None else _stages(), status="disabled",
    )
    cmd_create(
        conn, CONSUMER_FLOW, CONSUMER_PROJECT, "Consumer", "",
        _plain_stages(), status="disabled",
    )
    insert_item(
        conn, id=CARRIER_ITEM_ID, project_sequence=CARRIER_ITEM_ID,
        workflow_id="blitz", status="implementing", deployment_flow=CARRIER_FLOW,
    )
    insert_item(
        conn, id=CONSUMER_ITEM_ID, project_sequence=CONSUMER_ITEM_ID,
        workflow_id="blitz", status=consumer_status, project=CONSUMER_PROJECT,
        deployment_flow=CONSUMER_FLOW,
    )
    conn.commit()
    carrier_ref = item_ref(conn, CARRIER_ITEM_ID)
    consumer_ref = item_ref(conn, CONSUMER_ITEM_ID)
    consumer_id = _project_id(conn, CONSUMER_PROJECT)
    carrier_repo, carrier_base, carrier_tip = bound_source_repository(
        tmp_path, "carrier", carrier_ref
    )
    consumer_repo, consumer_base, consumer_tip = bound_source_repository(
        tmp_path, "consumer", consumer_ref
    )
    serve_repositories(monkeypatch, {1: carrier_repo, consumer_id: consumer_repo})
    insert_run(
        conn, "run-previous", lineage=carrier_base, status="succeeded",
        flow=CARRIER_FLOW,
        bound_sources=json.dumps(
            {
                "schema": 1,
                "projects": [
                    {
                        "project": CONSUMER_PROJECT,
                        "project_id": consumer_id,
                        "commit_sha": consumer_base,
                    }
                ],
                "inputs": {"consumer_sha": consumer_base},
            }
        ),
    )
    insert_run(
        conn, "run-candidate", lineage=carrier_tip, status="created",
        flow=CARRIER_FLOW,
    )
    return {
        "carrier_ref": carrier_ref,
        "consumer_ref": consumer_ref,
        "consumer_id": consumer_id,
        "consumer_repo": consumer_repo,
        "consumer_base": consumer_base,
        "consumer_tip": consumer_tip,
    }


def test_a_start_records_the_commit_each_bound_branch_names(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _two_project_release(test_db, tmp_path, monkeypatch)

    recorded = record_bound_sources(test_db, "run-candidate")

    assert recorded["inputs"] == {"consumer_sha": release["consumer_tip"]}
    assert recorded["projects"] == [
        {
            "project": CONSUMER_PROJECT,
            "project_id": release["consumer_id"],
            "commit_sha": release["consumer_tip"],
        }
    ]
    assert run_source_sha(
        test_db, "run-candidate", release["consumer_id"]
    ) == release["consumer_tip"]
    assert carried_project_ids(test_db, "run-candidate") == (
        1, release["consumer_id"]
    )


def test_a_recorded_commit_survives_the_branch_moving_under_it(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")

    git(release["consumer_repo"], "commit", "--allow-empty", "-m", "Later work")

    again = record_bound_sources(test_db, "run-candidate")
    assert again["inputs"] == {"consumer_sha": release["consumer_tip"]}


def test_a_bound_projects_landed_item_is_enrolled_by_the_carrying_run(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")

    enrolled = enroll_carried_members(test_db, "run-candidate")

    assert release["consumer_ref"] in enrolled
    assert release["carrier_ref"] in enrolled
    # The invariant enrollment exists to satisfy holds for both projects.
    assert carried_membership_refusal(test_db, "run-candidate") is None


def test_carried_work_answers_once_per_project_the_run_ships(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")

    payload = derive_carried_work(test_db, "run-candidate")

    bound = payload["bound_projects"]
    assert [entry["project_id"] for entry in bound] == [release["consumer_id"]]
    assert bound[0]["derivation"]["release_lineage"] == release["consumer_tip"]
    assert bound[0]["derivation"]["previous_release_lineage"] == (
        release["consumer_base"]
    )
    assert [entry["ref"] for entry in bound[0]["items"]] == [
        release["consumer_ref"]
    ]


def test_an_item_the_bound_commit_predates_is_not_enrolled(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _two_project_release(test_db, tmp_path, monkeypatch)
    # The consumer lands more work after the run resolved its binding, so the
    # recorded commit does not contain it.
    later_ref = item_ref(test_db, CONSUMER_ITEM_ID)
    record_bound_sources(test_db, "run-candidate")
    git(
        release["consumer_repo"], "commit", "--allow-empty", "-m",
        f"Land {later_ref} follow-up",
    )
    insert_item(
        test_db, id=UNBOUND_ITEM_ID, project_sequence=UNBOUND_ITEM_ID,
        workflow_id="blitz", status="implementing", project=CONSUMER_PROJECT,
        deployment_flow=CONSUMER_FLOW,
    )
    test_db.commit()

    enrolled = enroll_carried_members(test_db, "run-candidate")

    assert item_ref(test_db, UNBOUND_ITEM_ID) not in enrolled


def test_an_item_whose_project_the_run_ships_no_source_for_is_refused(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")
    insert_item(
        test_db, id=UNBOUND_ITEM_ID, project_sequence=UNBOUND_ITEM_ID,
        workflow_id="blitz", status="implementing", project=UNBOUND_PROJECT,
    )
    test_db.commit()

    with pytest.raises(WorkflowItemBindingError) as refusal:
        validate_deployment_run_item(
            test_db, run_id="run-candidate", item_id=UNBOUND_ITEM_ID
        )

    assert "ships no source for" in str(refusal.value)


def test_delivery_credits_the_commit_recorded_for_the_items_own_project(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")
    enroll_carried_members(test_db, "run-candidate")
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id='run-candidate'"
    )
    test_db.commit()

    evidence = delivery_evidence(test_db, CONSUMER_ITEM_ID)

    assert evidence.state == DISCHARGED
    assert evidence.run_id == "run-candidate"
    # The candidate a stricter caller must ask about is the consumer's
    # commit, not the carrier's lineage, which names nothing in that repo.
    assert evidence.release_lineage == release["consumer_tip"]
    assert evidence.project_id == release["consumer_id"]


def test_one_project_may_not_be_bound_to_two_branches_in_one_run(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stages = json.loads(_stages())
    stages.append(
        {
            "name": "second-release",
            "step_runner": "github-actions-workflow",
            "workflow": "other.yml",
            "stage_kind": "execution",
            "scope": "run",
            "input_bindings": {
                "consumer_sha": {"project": CONSUMER_PROJECT, "branch": "release"}
            },
        }
    )

    with pytest.raises(ValueError) as refusal:
        declared_bindings(stages)

    assert "declared twice with different sources" in str(refusal.value)


def test_a_retry_ships_the_commit_its_candidate_pinned(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")
    test_db.execute(
        "UPDATE deployment_runs SET status='failed' WHERE id='run-candidate'"
    )
    test_db.commit()
    from yoke_core.domain.deployment_run_bound_sources import copy_bound_sources

    insert_run(
        test_db, "run-retry", lineage=release["consumer_tip"], status="created",
        flow=CARRIER_FLOW,
    )
    git(release["consumer_repo"], "commit", "--allow-empty", "-m", "Later work")
    copy_bound_sources(test_db, "run-candidate", "run-retry")
    test_db.commit()

    inherited = parse_bound_sources(
        test_db.execute(
            "SELECT bound_sources FROM deployment_runs WHERE id='run-retry'"
        ).fetchone()[0]
    )
    assert inherited["inputs"] == {"consumer_sha": release["consumer_tip"]}
