"""The shared delivery ladder: membership, then containment, then honesty.

Enrolment in a deployment run is bookkeeping about how the run was
requested. Whether a release actually delivered an item is an ancestry fact.
These pin that the ladder reads the second when the first is absent, so two
members of one succeeded release cannot receive opposite verdicts.
"""

from yoke_core.domain import delivery_evidence_ladder as ladder
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    UNDETERMINED,
    ContainmentVerdict,
)


MERGE = "a" * 40
LINEAGE = "b" * 40


def _wire(
    monkeypatch,
    *,
    flow="yoke-prod-release",
    member=None,
    runs=(),
    persistent_runs=(),
    verdict=None,
    merge_sha=MERGE,
):
    monkeypatch.setattr(ladder, "_table_exists", lambda _conn, _table: True)
    monkeypatch.setattr(ladder, "item_completion_flow", lambda _c, _i: flow)
    monkeypatch.setattr(ladder, "latest_completion_run", lambda _c, _i: member)
    monkeypatch.setattr(ladder, "item_merge_identity", lambda _c, _i: merge_sha)
    monkeypatch.setattr(ladder, "_project_id", lambda _c, _i: 1)
    monkeypatch.setattr(
        ladder, "succeeded_flow_runs", lambda _c, **_kw: list(runs)
    )
    monkeypatch.setattr(
        ladder, "succeeded_persistent_runs", lambda _c, **_kw: list(persistent_runs)
    )
    if verdict is not None:
        monkeypatch.setattr(
            ladder,
            "candidate_contains_commit",
            lambda _c, _p, **_kw: verdict,
        )


def test_membership_on_a_succeeded_run_discharges_delivery(monkeypatch):
    _wire(
        monkeypatch,
        member={"id": "run-1", "status": "succeeded"},
    )
    verdict = ladder.delivery_evidence(object(), 1)
    assert verdict.discharged
    assert verdict.run_id == "run-1"
    assert verdict.source == ladder.SOURCE_MEMBERSHIP


def test_an_unenrolled_member_of_the_same_release_is_also_delivered(monkeypatch):
    """The case that gave two members of one run opposite verdicts."""
    _wire(
        monkeypatch,
        member=None,
        runs=[{"id": "run-4", "release_lineage": LINEAGE}],
        verdict=ContainmentVerdict(CONTAINED),
    )
    verdict = ladder.delivery_evidence(object(), 1)
    assert verdict.discharged
    assert verdict.run_id == "run-4"
    assert verdict.source == ladder.SOURCE_CONTAINMENT


def test_a_release_that_does_not_contain_the_merge_is_not_delivery(monkeypatch):
    _wire(
        monkeypatch,
        member=None,
        runs=[{"id": "run-4", "release_lineage": LINEAGE}],
        verdict=ContainmentVerdict(NOT_CONTAINED),
    )
    verdict = ladder.delivery_evidence(object(), 1)
    assert not verdict.discharged
    assert verdict.state == ladder.NOT_DISCHARGED
    assert verdict.recovery


def test_an_unreadable_comparison_is_undetermined_not_undelivered(monkeypatch):
    """A reader that could not look has not learned the item is undelivered."""
    _wire(
        monkeypatch,
        member=None,
        runs=[{"id": "run-4", "release_lineage": LINEAGE}],
        verdict=ContainmentVerdict(
            UNDETERMINED,
            "repository_provider_read_failed",
            "Confirm the binding, then retry.",
        ),
    )
    verdict = ladder.delivery_evidence(object(), 1)
    assert verdict.state == ladder.UNDETERMINED_DELIVERY
    assert not verdict.discharged
    assert "repository_provider_read_failed" in verdict.reason
    assert verdict.recovery


def test_a_definite_yes_on_an_older_run_beats_an_unreadable_newer_one(monkeypatch):
    """The walk keeps going: one unreadable release is not the answer."""
    seen: list[str] = []

    def _verdict(_conn, _project, *, candidate_lineage, commit_sha):
        seen.append(candidate_lineage)
        if candidate_lineage == "newer":
            return ContainmentVerdict(UNDETERMINED, "unreadable", "retry")
        return ContainmentVerdict(CONTAINED)

    _wire(
        monkeypatch,
        member=None,
        runs=[
            {"id": "run-9", "release_lineage": "newer"},
            {"id": "run-8", "release_lineage": "older"},
        ],
    )
    monkeypatch.setattr(ladder, "candidate_contains_commit", _verdict)
    verdict = ladder.delivery_evidence(object(), 1)
    assert verdict.discharged
    assert verdict.run_id == "run-8"
    assert seen == ["newer", "older"]


def test_a_prepared_run_is_named_rather_than_reported_missing(monkeypatch):
    _wire(
        monkeypatch,
        member={"id": "run-7", "status": "created"},
        runs=[],
    )
    verdict = ladder.delivery_evidence(object(), 1)
    assert not verdict.discharged
    assert verdict.run_id == "run-7"
    assert "run-7" in verdict.recovery


def test_an_item_with_no_flow_closes_on_the_run_that_carried_it(monkeypatch):
    """A flow it can never store is not a reason to strand a delivered item."""
    _wire(
        monkeypatch,
        flow="",
        persistent_runs=[{"id": "run-14", "release_lineage": LINEAGE}],
        verdict=ContainmentVerdict(CONTAINED),
    )
    verdict = ladder.delivery_evidence(object(), 1)
    assert verdict.discharged
    assert verdict.run_id == "run-14"
    assert verdict.source == ladder.SOURCE_CONTAINMENT


def test_an_item_with_no_flow_is_not_closed_by_an_unrelated_run(monkeypatch):
    """Standing in for the flow widens which runs are asked, not the answer."""
    _wire(
        monkeypatch,
        flow="",
        persistent_runs=[{"id": "run-15", "release_lineage": LINEAGE}],
        verdict=ContainmentVerdict(NOT_CONTAINED),
    )
    verdict = ladder.delivery_evidence(object(), 1)
    assert verdict.state == ladder.NOT_DISCHARGED
    assert "stores no deployment flow" in verdict.reason
    assert "persistent environment" in verdict.recovery


def test_an_item_with_no_flow_never_asks_the_selected_flow_rung(monkeypatch):
    """There is no flow to ask about, so the walk reads the project's runs."""
    def _refuse(*_args, **_kwargs):
        raise AssertionError("a flow-less item has no selected-flow runs")

    _wire(
        monkeypatch,
        flow="",
        persistent_runs=[],
        verdict=ContainmentVerdict(NOT_CONTAINED),
    )
    monkeypatch.setattr(ladder, "succeeded_flow_runs", _refuse)
    verdict = ladder.delivery_evidence(object(), 1)
    assert verdict.state == ladder.NOT_DISCHARGED


def test_the_verdict_carries_the_run_candidate_for_a_stricter_caller(monkeypatch):
    """Delivery happened and containment are two questions, not one.

    A run can list an item as a member while shipping a revision that
    predates its merge. The ladder answers only the first, so it hands back
    the run's own candidate rather than letting a caller with the stricter
    question believe it was already checked.
    """
    _wire(
        monkeypatch,
        member={
            "id": "run-1",
            "status": "succeeded",
            "release_lineage": LINEAGE,
            "project_id": 7,
        },
    )
    verdict = ladder.delivery_evidence(object(), 1)
    assert verdict.discharged
    assert verdict.release_lineage == LINEAGE
    assert verdict.project_id == 7
