"""Outside commits ship through creation, admission, freeze and settlement."""

from typing import Any
from pathlib import Path

from runtime.api.fixtures.bound_source_release import two_project_release
from runtime.api.fixtures.release_output_source import carried_work_of
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_create_write import cmd_create_run
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition

pytest_plugins = ("runtime.api.fixtures.release_output_fixture",)


def test_a_run_carries_outside_commits_without_attestation_or_resolution(
    test_db: Any,
    release_source: dict[str, Any],
) -> None:
    run_id = cmd_create_run(
        release_source["project"],
        "release-output-flow",
        release_lineage=release_source["maintenance"],
    )
    valid, message = cmd_validate_composition(run_id)
    assert valid, message
    assert cmd_update(run_id, "status", "executing") is None
    carried = carried_work_of(test_db, run_id)
    assert carried["commits"] == [release_source["pin"], release_source["maintenance"]]
    assert (
        carried["commit_subjects"][release_source["maintenance"]]
        == "Routine maintenance"
    )
    assert carried["commit_authors"] == {sha: "Yoke Test" for sha in carried["commits"]}
    assert cmd_update(run_id, "status", "succeeded") is None
    row = test_db.execute(
        "SELECT status,composition_resolution FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    assert row[0] == "succeeded"
    assert not row[1]
    assert carried_work_of(test_db, run_id) == carried


def test_outside_work_is_recorded_under_the_bound_project_that_carries_it(
    test_db: Any,
    tmp_path: Path,
    monkeypatch,
) -> None:
    release = two_project_release(
        test_db, tmp_path, monkeypatch, consumer_receipt=False
    )
    record_bound_sources(test_db, "run-candidate")
    valid, message = cmd_validate_composition("run-candidate")
    assert valid, message
    carried = derive_carried_work(test_db, "run-candidate")
    consumer = carried["bound_projects"][0]
    assert consumer["project"] == "consumer"
    assert consumer["commits"] == [release["consumer_tip"]]
    assert consumer["commit_authors"][release["consumer_tip"]] == "Yoke Test"
    assert (
        consumer["commit_subjects"][release["consumer_tip"]] == "Land product changes"
    )
