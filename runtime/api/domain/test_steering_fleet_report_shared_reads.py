"""One request shares coherent per-PR reads across all held scopes."""

from __future__ import annotations

from collections import Counter

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.steering_fleet_test_helpers import (
    ACTOR_ID,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    STEERING_SESSION,
    seed_relay,
    seed_session,
)
from yoke_core.domain import merge_queue_read_reuse as reads_mod
from yoke_core.domain import steering_fleet_report as fleet_report
from yoke_core.domain import steering_fleet_report_reads as reads_module
from yoke_core.domain.merge_queue_read_reuse import MergeQueueReads
from yoke_core.domain.steering_claims import acquire as acquire_steering
from yoke_core.domain.steering_fleet_report_compose import compose_held_reports
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_reads import FleetReportReads
from yoke_core.domain.strategy_docs_create import create_doc
from yoke_core.domain.strategy_docs_defaults import seed_default_docs
from yoke_core.engines.merge_worktree_pr_check_runs import PrLandingProjection
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


FIRST_DOCUMENT = "AREA-PLAN-ONE"
SECOND_DOCUMENT = "AREA-PLAN-TWO"
UNREADABLE_PR = "pull-request landing read failed"


def _link(conn, item_id: int, slug: str) -> None:
    conn.execute(
        "INSERT INTO item_strategy_docs "
        "(item_id, project_id, strategy_doc_slug, linked_by_actor_id, linked_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (item_id, PROJECT_ID, slug, ACTOR_ID, LONG_AGO),
    )


@pytest.fixture
def two_seats(test_db):
    """One session holding two document seats, each with one open landing."""
    seed_session(test_db, STEERING_SESSION)
    seed_relay(test_db)
    for item_id in (1, 2):
        insert_item(
            test_db,
            id=item_id,
            title=f"Landing work {item_id}",
            status="implementing",
            created_at=LONG_AGO,
            updated_at=LONG_AGO,
            spec=f"# Landing work {item_id}\n\nA real spec body.",
        )
    test_db.execute(
        "UPDATE items SET merge_queue_pr_number=CAST(id AS TEXT), "
        "merge_queue_enqueued_at=%s WHERE id IN (1,2)",
        (LONG_AGO,),
    )
    test_db.commit()
    seed_default_docs(test_db, PROJECT_ID, "Yoke")
    create_doc(
        test_db,
        PROJECT_ID,
        FIRST_DOCUMENT,
        "# one\n",
        actor_id=ACTOR_ID,
        summary="Strategy document.",
        state="draft",
    )
    create_doc(
        test_db,
        PROJECT_ID,
        SECOND_DOCUMENT,
        "# two\n",
        actor_id=ACTOR_ID,
        summary="Strategy document.",
        state="draft",
    )
    _link(test_db, 1, FIRST_DOCUMENT)
    _link(test_db, 2, SECOND_DOCUMENT)
    test_db.commit()
    for document in (FIRST_DOCUMENT, SECOND_DOCUMENT):
        acquire_steering(
            test_db,
            session_id=STEERING_SESSION,
            project_id=PROJECT_ID,
            reason="steering",
            document=document,
        )
    return test_db


def _wire_github(monkeypatch, *, pr_error: str = "") -> Counter:
    """Count PR projections and fail if the branch queue is read."""
    calls: Counter[str] = Counter()

    def projection(_ctx, pr_number, **_kwargs):
        calls[f"pr_projection:{pr_number}"] += 1
        if pr_error:
            return PrLandingProjection(state_error=pr_error, checks_error=pr_error)
        return PrLandingProjection(
            state=PrLandingState(False, False, False, merge_state_status="blocked",
                                 queue_entry_state="AWAITING_CHECKS"),
            required_checks=(),
        )

    def queue_members(*_args, **_kwargs):
        pytest.fail("fleet report must not read the branch queue")

    monkeypatch.setattr(reads_mod, "read_pr_landing_and_required_checks", projection)
    monkeypatch.setattr("yoke_core.engines.merge_worktree_pr_queue.read_queue_members",
                        queue_members)
    return calls


def _compose_alone(conn, scope: dict):
    """The same scope composed as the only scope of its own request."""
    return fleet_report.compose_report(
        conn,
        project_id=PROJECT_ID,
        session_id=STEERING_SESSION,
        staffing_after_seconds=300,
        idle_after_seconds=1200,
        now=NOW,
        scope=scope,
        reads=FleetReportReads(),
    )


def test_fleet_reads_coherent_pr_entries_without_the_branch_queue(
    two_seats, monkeypatch
) -> None:
    calls = _wire_github(monkeypatch)

    combined = compose_held_reports(two_seats, session_id=STEERING_SESSION, now=NOW)

    assert [len(section.report.landings) for section in combined.sections] == [1, 1]
    assert calls["pr_projection:1"] == 1
    assert calls["pr_projection:2"] == 1
    for section in combined.sections:
        readiness = section.report.landings[0].readiness
        assert readiness.queue_holding == "enqueued"
        assert readiness.landing_state == "in_flight"
        assert readiness.queue_entry_state == "AWAITING_CHECKS"
        assert readiness.merge_when_ready == "consumed"


def test_project_facts_are_read_once_and_each_scope_narrows_them(
    two_seats, monkeypatch
) -> None:
    _wire_github(monkeypatch)
    reads: list[int] = []
    original = reads_module.read_project_facts

    def counted(*args, **kwargs):
        reads.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(reads_module, "read_project_facts", counted)

    combined = compose_held_reports(two_seats, session_id=STEERING_SESSION, now=NOW)

    assert len(reads) == 1
    assert [section.descriptor for section in combined.sections] == [
        f"yoke · {FIRST_DOCUMENT}",
        f"yoke · {SECOND_DOCUMENT}",
    ]
    alone = {
        section.descriptor: _compose_alone(
            two_seats,
            {"project_id": PROJECT_ID, "document": section.descriptor.split(" · ")[1]},
        )
        for section in combined.sections
    }
    for section in combined.sections:
        assert report_dict(section.report) == report_dict(alone[section.descriptor])


def test_failed_pr_reads_stay_unreadable_for_every_landing(
    two_seats, monkeypatch
) -> None:
    _wire_github(monkeypatch, pr_error=UNREADABLE_PR)

    combined = compose_held_reports(two_seats, session_id=STEERING_SESSION, now=NOW)

    for section in combined.sections:
        readiness = section.report.landings[0].readiness
        assert readiness.queue_entry_state == "unreadable"
        assert UNREADABLE_PR in readiness.warnings


def test_a_landing_fact_is_read_once_per_pull_request_and_repository(
    monkeypatch,
) -> None:
    calls = _wire_github(monkeypatch)
    reads = MergeQueueReads()
    here = MergeContext(args=MergeArgs(branch="", target="main"), project="yoke")
    elsewhere = MergeContext(
        args=MergeArgs(branch="", target="main"), project="platform"
    )

    for _ in range(3):
        reads.pr_landing_state(here, "42")
        reads.required_checks(here, "42")
    reads.pr_landing_state(elsewhere, "42")

    assert calls["pr_projection:42"] == 2


def test_a_request_of_its_own_reads_for_itself(monkeypatch) -> None:
    """A caller that shares nothing still gets the same answers."""
    calls = _wire_github(monkeypatch)
    ctx = MergeContext(args=MergeArgs(branch="", target="main"), project="yoke")

    first = MergeQueueReads().pr_landing_state(ctx, "42")
    second = MergeQueueReads().pr_landing_state(ctx, "42")

    assert first == second
    assert calls["pr_projection:42"] == 2
