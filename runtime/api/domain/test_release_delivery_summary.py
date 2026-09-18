"""A releasing item's merge counts, and what makes one of them deployed.

Both halves read records the control plane already keeps: the landings the
item itself recorded, and the succeeded runs to its environment. The case
worth naming is the merge that reached the base branch under a *different*
item's landing — no run ever lists it for this item, yet it is deployed, and
only ancestry says so.
"""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog_inserts import insert_deployment_run
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import release_delivery_summary as summary_module
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    ContainmentVerdict,
)
from yoke_core.domain.release_delivery_summary import delivery_summary

ITEM_ID = 4201
PROJECT_ID = 1
ENVIRONMENT_ID = 7
OWN_MERGE = "a" * 40
CROSS_ITEM_MERGE = "b" * 40
UNSHIPPED_MERGE = "c" * 40
LINEAGE = "d" * 40


def _record_landing(conn, merge_sha: str, requirement_id: int, run_id: int) -> None:
    """Write the passing ci_run row a landing records its merge on."""
    conn.execute(
        "INSERT INTO qa_requirements (id, item_id, qa_kind, qa_phase, "
        "blocking_mode, created_at) VALUES "
        "(%s,%s,'plan_case','verification','blocking','2026-09-18T00:00:00Z')",
        (requirement_id, ITEM_ID),
    )
    conn.execute(
        "INSERT INTO qa_runs (id, qa_requirement_id, qa_kind, performed_by, "
        "verdict, raw_result, created_at) VALUES "
        "(%s,%s,'plan_case','ci_run','pass',%s,'2026-09-18T00:00:00Z')",
        (
            run_id,
            requirement_id,
            json.dumps({
                "merge_queue_batch": {
                    "pr_num": str(1200 + run_id),
                    "merge_sha": merge_sha,
                    "combined_head_sha": LINEAGE,
                    "run_url": "https://example.test/run",
                },
            }),
        ),
    )


def _succeeded_run(conn, run_id: str, *, carried: list[str]) -> None:
    """A succeeded release to this item's environment, carrying ``carried``."""
    insert_deployment_run(
        conn,
        id=run_id,
        project_id=PROJECT_ID,
        status="succeeded",
        # The schema pairs a persistent tier with a named environment.
        target_tier="persistent",
        release_lineage=LINEAGE,
        target_environment_id=ENVIRONMENT_ID,
        carried_work=json.dumps(
            {"items": [{"ref": "YOK-1", "commit_shas": carried}]}
        ),
        completed_at="2026-09-18T00:00:00Z",
    )


def _summary(conn):
    return delivery_summary(
        conn,
        item_id=ITEM_ID,
        project_id=PROJECT_ID,
        environment_id=ENVIRONMENT_ID,
    )


def test_an_item_with_no_recorded_landing_has_no_merges() -> None:
    with test_database() as conn:
        result = _summary(conn)

    assert (result.merges, result.deployed, result.not_deployed) == (0, 0, 0)


def test_a_merge_a_succeeded_run_carried_is_deployed() -> None:
    with test_database() as conn:
        _record_landing(conn, OWN_MERGE, 1, 1)
        _succeeded_run(conn, "run-1", carried=[OWN_MERGE])
        conn.commit()

        result = _summary(conn)

    assert (result.merges, result.deployed, result.not_deployed) == (1, 1, 0)


def test_a_merge_no_run_has_carried_yet_is_not_deployed(monkeypatch) -> None:
    """The state the line exists to surface: landed, still waiting."""
    monkeypatch.setattr(
        summary_module,
        "candidate_contains_commit",
        lambda *a, **k: ContainmentVerdict(state=NOT_CONTAINED),
    )
    with test_database() as conn:
        _record_landing(conn, UNSHIPPED_MERGE, 1, 1)
        _succeeded_run(conn, "run-1", carried=[OWN_MERGE])
        conn.commit()

        result = _summary(conn)

    assert (result.merges, result.deployed, result.not_deployed) == (1, 0, 1)


def test_a_merge_carried_under_another_items_landing_counts_as_deployed(
    monkeypatch,
) -> None:
    """No run names it for this item, but the release contains it."""
    seen: list[str] = []

    def _contains(conn, project_id, *, candidate_lineage, commit_sha):
        seen.append(commit_sha)
        return ContainmentVerdict(
            state=CONTAINED if commit_sha == CROSS_ITEM_MERGE else NOT_CONTAINED,
        )

    monkeypatch.setattr(summary_module, "candidate_contains_commit", _contains)
    with test_database() as conn:
        _record_landing(conn, CROSS_ITEM_MERGE, 1, 1)
        # The run carries somebody else's commits, never this item's.
        _succeeded_run(conn, "run-1", carried=["e" * 40])
        conn.commit()

        result = _summary(conn)

    assert (result.merges, result.deployed, result.not_deployed) == (1, 1, 0)
    assert seen == [CROSS_ITEM_MERGE]


def test_counts_cover_every_distinct_recorded_landing(monkeypatch) -> None:
    monkeypatch.setattr(
        summary_module,
        "candidate_contains_commit",
        lambda *a, **k: ContainmentVerdict(state=NOT_CONTAINED),
    )
    with test_database() as conn:
        _record_landing(conn, OWN_MERGE, 1, 1)
        _record_landing(conn, UNSHIPPED_MERGE, 2, 2)
        # A second recording of the same merge is one merge, not two.
        _record_landing(conn, OWN_MERGE, 3, 3)
        _succeeded_run(conn, "run-1", carried=[OWN_MERGE])
        conn.commit()

        result = _summary(conn)

    assert (result.merges, result.deployed, result.not_deployed) == (2, 1, 1)


def test_an_item_with_no_resolvable_environment_reports_nothing_deployed(
    monkeypatch,
) -> None:
    """A flow with no target environment cannot say a merge shipped."""
    monkeypatch.setattr(
        summary_module,
        "candidate_contains_commit",
        lambda *a, **k: ContainmentVerdict(state=NOT_CONTAINED),
    )
    with test_database() as conn:
        _record_landing(conn, OWN_MERGE, 1, 1)
        _succeeded_run(conn, "run-1", carried=[OWN_MERGE])
        conn.commit()

        result = delivery_summary(
            conn, item_id=ITEM_ID, project_id=PROJECT_ID, environment_id=None
        )

    assert (result.merges, result.deployed, result.not_deployed) == (1, 0, 1)


def test_only_the_newest_release_lineage_is_asked(monkeypatch) -> None:
    """Containment carries forward, so older runs add cost and no answer."""
    asked: list[str] = []

    def _contains(conn, project_id, *, candidate_lineage, commit_sha):
        asked.append(candidate_lineage)
        return ContainmentVerdict(state=CONTAINED)

    monkeypatch.setattr(summary_module, "candidate_contains_commit", _contains)
    newest = "1" * 40
    with test_database() as conn:
        _record_landing(conn, CROSS_ITEM_MERGE, 1, 1)
        _succeeded_run(conn, "run-old", carried=[])
        _succeeded_run(conn, "run-older", carried=[])
        conn.execute(
            "UPDATE deployment_runs SET release_lineage=%s, "
            "completed_at='2026-09-18T12:00:00Z' WHERE id='run-old'",
            (newest,),
        )
        conn.commit()

        result = _summary(conn)

    assert result.deployed == 1
    # One question, against the newest lineage — not one per run.
    assert asked == [newest]
