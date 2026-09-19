"""Carried work reads the release that wrote a commit, and only then.

A promotion that rewrites a version pin pushes a commit no backlog item
authored. Left unexplained it is unattributed carried work, and the next
release refuses to compose until somebody records a resolution by hand — so
the run that produced it records it, and attribution reads that record.

What these tests hold down is the ordering: the record is consulted only for
a commit attribution had already given up on, and explaining one commit
explains nothing else in the same range.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures.release_output_source import (
    carried_work_of,
    insert_run,
)
from yoke_core.domain import deployment_runs
from yoke_core.domain.deployment_run_carried_membership import (
    carried_membership_refusal,
)
from yoke_core.domain.deployment_run_release_output_record import (
    OUTCOME_RECORDED,
    record_release_output,
)


pytest_plugins = ("runtime.api.fixtures.release_output_fixture",)


def test_a_recorded_pin_commit_composes_without_a_hand_written_resolution(
    test_db: Any, release_source: dict[str, Any]
) -> None:
    """The release that wrote the commit is the attribution the next one reads."""
    receipt = record_release_output(
        test_db,
        run_id=release_source["producer"],
        project=release_source["project"],
        commit_sha=release_source["pin"],
    )
    test_db.commit()
    assert receipt["outcome"] == OUTCOME_RECORDED
    insert_run(
        test_db,
        "run-release-output-002",
        release_source["pin"],
        flow_id="release-output-flow",
        status="executing",
        created_at="2026-09-19T00:03:00Z",
    )

    assert deployment_runs.cmd_update(
        "run-release-output-002", "status", "succeeded"
    ) is None

    carried = carried_work_of(test_db, "run-release-output-002")
    assert carried["commits"] == []
    assert [entry["commit_sha"] for entry in carried["release_output"]] == [
        release_source["pin"]
    ]
    assert carried["release_output"][0]["run_id"] == release_source["producer"]
    assert carried_membership_refusal(test_db, "run-release-output-002") is None


def test_an_unexplained_commit_beside_a_recorded_one_still_refuses(
    test_db: Any, release_source: dict[str, Any]
) -> None:
    """Attributing release output waives nothing else in the same range."""
    record_release_output(
        test_db,
        run_id=release_source["producer"],
        project=release_source["project"],
        commit_sha=release_source["pin"],
    )
    test_db.commit()
    insert_run(
        test_db,
        "run-release-output-003",
        release_source["maintenance"],
        flow_id="release-output-flow",
        status="executing",
        created_at="2026-09-19T00:04:00Z",
    )

    assert deployment_runs.cmd_update(
        "run-release-output-003", "status", "succeeded"
    ) is None

    carried = carried_work_of(test_db, "run-release-output-003")
    assert carried["commits"] == [release_source["maintenance"]]
    refusal = carried_membership_refusal(test_db, "run-release-output-003")
    assert refusal is not None
    assert "1 unattributed carried commit(s)" in refusal
