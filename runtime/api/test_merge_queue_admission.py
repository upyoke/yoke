"""Train-composition admission classifier behavior."""

from runtime.api.merge_queue_landing_test_helpers import dispatch_for, land
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain.merge_queue_admission import (
    ADMIT,
    REFUSE_MIGRATION_CARRIER,
    REFUSE_SERIAL_ORDERING,
    REFUSE_UNATTESTED_OVERLAP,
    TrainCandidate,
    TrainContext,
    evaluate_admission,
)
from yoke_core.engines.merge_worktree_pr_queue import QueueMember


def _candidate(ref="YOK-A", targets=(), carrier=False, landed=False):
    return TrainCandidate(
        public_ref=ref,
        claimed_target_ids=frozenset(targets),
        migration_carrier=carrier,
        landed=landed,
    )


def test_empty_queue_admits():
    verdict = evaluate_admission(_candidate(), TrainContext())
    assert verdict.admit
    assert verdict.reason == ADMIT
    assert "clear" in verdict.narrative()


def test_disjoint_members_admit():
    context = TrainContext(
        members=(
            _candidate("YOK-B", targets=(11, 12)),
            _candidate("YOK-C", targets=(13,)),
        )
    )
    verdict = evaluate_admission(_candidate(targets=(21, 22)), context)
    assert verdict.admit


def test_unattested_overlap_refuses_and_names_members():
    context = TrainContext(
        members=(
            _candidate("YOK-B", targets=(11, 21)),
            _candidate("YOK-C", targets=(13,)),
        )
    )
    verdict = evaluate_admission(_candidate(targets=(21,)), context)
    assert not verdict.admit
    assert verdict.reason == REFUSE_UNATTESTED_OVERLAP
    assert verdict.conflicting_members == ("YOK-B",)
    assert "YOK-B" in verdict.narrative()


def test_coordination_attested_overlap_admits():
    context = TrainContext(
        members=(_candidate("YOK-B", targets=(21,)),),
        coordination_attested_refs=frozenset({"YOK-B"}),
    )
    verdict = evaluate_admission(_candidate(targets=(21,)), context)
    assert verdict.admit


def test_unlanded_predecessor_refuses_even_without_path_overlap():
    context = TrainContext(
        members=(_candidate("YOK-B", targets=(11,)),),
        predecessor_refs=frozenset({"YOK-B"}),
    )
    verdict = evaluate_admission(_candidate(targets=(21,)), context)
    assert not verdict.admit
    assert verdict.reason == REFUSE_SERIAL_ORDERING
    assert verdict.conflicting_members == ("YOK-B",)
    assert "has not landed" in verdict.narrative()
    assert "yoke merge item" in verdict.narrative()


def test_unlanded_candidate_refuses_against_its_queued_dependent():
    context = TrainContext(
        members=(_candidate("YOK-B"),),
        dependent_refs=frozenset({"YOK-B"}),
    )
    verdict = evaluate_admission(_candidate(), context)
    assert not verdict.admit
    assert verdict.reason == REFUSE_SERIAL_ORDERING


def test_landed_candidate_correction_admits_beside_its_queued_dependent():
    context = TrainContext(
        members=(_candidate("YOK-B"),),
        dependent_refs=frozenset({"YOK-B"}),
    )
    verdict = evaluate_admission(_candidate(landed=True), context)
    assert verdict.admit


def test_correction_of_landed_predecessor_admits_beside_candidate():
    context = TrainContext(
        members=(_candidate("YOK-B", landed=True),),
        predecessor_refs=frozenset({"YOK-B"}),
    )
    verdict = evaluate_admission(_candidate(landed=True), context)
    assert verdict.admit


def test_landed_candidate_still_waits_on_an_unlanded_predecessor():
    context = TrainContext(
        members=(_candidate("YOK-B"),),
        predecessor_refs=frozenset({"YOK-B"}),
    )
    verdict = evaluate_admission(_candidate(landed=True), context)
    assert not verdict.admit
    assert verdict.reason == REFUSE_SERIAL_ORDERING


def test_serial_link_outranks_attested_overlap():
    context = TrainContext(
        members=(_candidate("YOK-B", targets=(21,)),),
        coordination_attested_refs=frozenset({"YOK-B"}),
        predecessor_refs=frozenset({"YOK-B"}),
    )
    verdict = evaluate_admission(_candidate(targets=(21,)), context)
    assert not verdict.admit
    assert verdict.reason == REFUSE_SERIAL_ORDERING


def test_second_migration_carrier_refuses():
    context = TrainContext(
        members=(
            _candidate("YOK-B", carrier=True),
            _candidate("YOK-C"),
        )
    )
    verdict = evaluate_admission(_candidate(carrier=True), context)
    assert not verdict.admit
    assert verdict.reason == REFUSE_MIGRATION_CARRIER
    assert verdict.conflicting_members == ("YOK-B",)


def test_non_carrier_joins_carrier_train():
    context = TrainContext(members=(_candidate("YOK-B", carrier=True),))
    verdict = evaluate_admission(_candidate(), context)
    assert verdict.admit


def _queued_member(monkeypatch):
    monkeypatch.setattr(
        route_mod,
        "read_queue_members",
        lambda ctx, base_branch="main": (
            [QueueMember(pr_num="9", head_ref="YOK-150")],
            None,
        ),
    )


def test_route_refuses_a_serial_dependency_already_in_the_queue(monkeypatch):
    _queued_member(monkeypatch)
    shapes = {
        "YOK-200": {
            "claims": [],
            "dependencies": [
                {
                    "direction": "depends-on",
                    "other_item": "YOK-150",
                    "gate_point": "activation",
                }
            ],
        },
        "YOK-150": {"claims": []},
    }

    outcome = land(dispatch=dispatch_for(shapes))

    assert not outcome.ok
    assert "serial-ordering" in outcome.error


def test_route_resolves_migration_carriers_from_the_item_profile(monkeypatch):
    _queued_member(monkeypatch)
    shapes = {
        "YOK-200": {"profile": '{"state":"declared"}'},
        "YOK-150": {"profile": '{"state":"declared"}'},
    }

    outcome = land(dispatch=dispatch_for(shapes))

    assert not outcome.ok
    assert "migration-carrier-limit" in outcome.error
