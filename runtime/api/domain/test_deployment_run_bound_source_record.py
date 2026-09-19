"""One run, one recorded source commit per project it ships.

A bound branch moves. The whole point of resolving it once and storing the
answer is that a retry, a later reader and the build that actually shipped
all name the same commit, so these tests move the branch under a recorded
run and assert the record does not follow it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.bound_source_release import (
    CARRIER_FLOW,
    CONSUMER_PROJECT,
    bound_stages,
    two_project_release,
)
from runtime.api.fixtures.carried_release_candidate import git, insert_run
from yoke_core.domain.deployment_run_bound_sources import (
    copy_bound_sources,
    declared_bindings,
    parse_bound_sources,
    record_bound_sources,
)
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_project_sources import (
    carried_project_ids,
    run_source_sha,
)


def test_a_start_records_the_commit_each_bound_branch_names(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)

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
    release = two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")

    git(release["consumer_repo"], "commit", "--allow-empty", "-m", "Later work")

    again = record_bound_sources(test_db, "run-candidate")
    assert again["inputs"] == {"consumer_sha": release["consumer_tip"]}


def test_carried_work_answers_once_per_project_the_run_ships(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)
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


def test_one_project_may_not_be_bound_to_two_branches_in_one_run(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stages = json.loads(bound_stages())
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
    release = two_project_release(test_db, tmp_path, monkeypatch)
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
