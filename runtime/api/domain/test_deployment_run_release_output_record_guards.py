"""Recording a release's own commit is guarded, never trusted.

A record that could absorb any commit would waive exactly the delivery proof
composition validation exists to demand. So four claims are checked before
one is written, and each refusal names itself: the ref resolves, the commit
is not merely the one the run pinned, it descends from that pinned source,
and no backlog item already owns it.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.release_output_source import (  # noqa: F401
    git,
    insert_flow,
    insert_run,
    release_source,
)
from yoke_core.domain.deployment_run_release_output_record import (
    OUTCOME_NOTHING_PRODUCED,
    OUTCOME_RECORDED,
    ReleaseOutputRefused,
    record_release_output,
)

ITEM_REF = "YOK-9601"


def test_recording_refuses_a_commit_a_backlog_item_already_owns(
    test_db: Any, release_source: dict[str, Any]
) -> None:
    """An item's commit is that item's work however the caller labels it."""
    insert_item(
        test_db,
        id=9601,
        project_sequence=9601,
        workflow_id="dash",
        status="done",
    )
    repo = release_source["repo"]
    (repo / "release.txt").write_text("item work\n", encoding="utf-8")
    git(repo, "commit", "-am", f"Land {ITEM_REF} product changes")
    item_commit = git(repo, "rev-parse", "HEAD")
    test_db.commit()

    with pytest.raises(ReleaseOutputRefused) as refusal:
        record_release_output(
            test_db,
            run_id=release_source["producer"],
            project=release_source["project"],
            commit_sha=item_commit,
        )

    assert refusal.value.reason == "commit_attributed_to_item"
    assert ITEM_REF in str(refusal.value)


def test_recording_refuses_a_commit_only_a_lane_record_claims(
    test_db: Any, release_source: dict[str, Any]
) -> None:
    """Ownership can be recorded on the lane rather than in the message.

    An item whose landed lane head is this commit owns it just as surely as
    one that named itself in the subject line. Reading that needs a range the
    commit is actually inside, which is why the guard asks from the commit's
    parent rather than from the commit itself.
    """
    repo = release_source["repo"]
    (repo / "release.txt").write_text("quiet lane work\n", encoding="utf-8")
    git(repo, "commit", "-am", "Tidy the release notes")
    lane_commit = git(repo, "rev-parse", "HEAD")
    insert_item(
        test_db,
        id=9611,
        project_sequence=9611,
        workflow_id="dash",
        status="done",
        merged_at="2026-09-19T00:03:00Z",
    )
    test_db.execute(
        "INSERT INTO item_worktrees("
        "item_id,branch,path,lane_role,state,commit_sha,created_at,updated_at) "
        "VALUES (9611,'YOK-9611','/lane','implementation','released',%s,"
        "'2026-09-19T00:02:00Z','2026-09-19T00:03:00Z')",
        (lane_commit,),
    )
    test_db.commit()

    with pytest.raises(ReleaseOutputRefused) as refusal:
        record_release_output(
            test_db,
            run_id=release_source["producer"],
            project=release_source["project"],
            commit_sha=lane_commit,
        )

    assert refusal.value.reason == "commit_attributed_to_item"


def test_recording_refuses_a_commit_that_predates_the_pinned_source(
    test_db: Any, release_source: dict[str, Any]
) -> None:
    """A run cannot have produced a commit its own pinned source already held."""
    insert_run(
        test_db,
        "run-release-output-004",
        release_source["maintenance"],
        flow_id="release-output-flow",
        status="succeeded",
        created_at="2026-09-19T00:05:00Z",
        completed_at="2026-09-19T00:06:00Z",
    )

    with pytest.raises(ReleaseOutputRefused) as refusal:
        record_release_output(
            test_db,
            run_id="run-release-output-004",
            project=release_source["project"],
            commit_sha=release_source["baseline"],
        )

    assert refusal.value.reason == "commit_precedes_pinned_source"


def test_an_unnamed_commit_resolves_the_branch_the_run_itself_bound(
    test_db: Any, release_source: dict[str, Any]
) -> None:
    """The caller names a project; the flow's own binding names the branch.

    A promotion that pushed nothing leaves that branch where the run pinned
    it, and the receipt says the release produced no commit rather than
    inventing a record for the commit it merely shipped.
    """
    insert_flow(test_db, "release-output-bound-flow", binds_own_trunk=True)
    insert_run(
        test_db,
        "run-release-output-005",
        release_source["maintenance"],
        flow_id="release-output-bound-flow",
        status="executing",
        created_at="2026-09-19T00:07:00Z",
    )

    quiet = record_release_output(
        test_db,
        run_id="run-release-output-005",
        project=release_source["project"],
    )
    assert quiet["outcome"] == OUTCOME_NOTHING_PRODUCED
    assert quiet["commit_sha"] == ""

    repo = release_source["repo"]
    (repo / "yoke-release-pin.txt").write_text("0.1.1+launch.460\n", encoding="utf-8")
    git(repo, "commit", "-am", "Pin prod Yoke 0.1.1+launch.460")
    pushed = git(repo, "rev-parse", "HEAD")

    recorded = record_release_output(
        test_db,
        run_id="run-release-output-005",
        project=release_source["project"],
    )

    assert recorded["outcome"] == OUTCOME_RECORDED
    assert recorded["commit_sha"] == pushed
