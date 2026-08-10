"""Train-composition admission classifier behavior."""

from yoke_core.domain.merge_queue_admission import (
    ADMIT,
    REFUSE_MIGRATION_CARRIER,
    REFUSE_SERIAL_ORDERING,
    REFUSE_UNATTESTED_OVERLAP,
    TrainCandidate,
    TrainContext,
    evaluate_admission,
)


def _candidate(ref="YOK-A", targets=(), carrier=False):
    return TrainCandidate(
        item_ref=ref,
        claimed_target_ids=frozenset(targets),
        migration_carrier=carrier,
    )


def test_empty_queue_admits():
    verdict = evaluate_admission(_candidate(), TrainContext())
    assert verdict.admit
    assert verdict.reason == ADMIT
    assert "clear" in verdict.narrative()


def test_disjoint_members_admit():
    context = TrainContext(members=(
        _candidate("YOK-B", targets=(11, 12)),
        _candidate("YOK-C", targets=(13,)),
    ))
    verdict = evaluate_admission(_candidate(targets=(21, 22)), context)
    assert verdict.admit


def test_unattested_overlap_refuses_and_names_members():
    context = TrainContext(members=(
        _candidate("YOK-B", targets=(11, 21)),
        _candidate("YOK-C", targets=(13,)),
    ))
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


def test_serial_link_refuses_even_without_path_overlap():
    context = TrainContext(
        members=(_candidate("YOK-B", targets=(11,)),),
        serial_linked_refs=frozenset({"YOK-B"}),
    )
    verdict = evaluate_admission(_candidate(targets=(21,)), context)
    assert not verdict.admit
    assert verdict.reason == REFUSE_SERIAL_ORDERING


def test_serial_link_outranks_attested_overlap():
    context = TrainContext(
        members=(_candidate("YOK-B", targets=(21,)),),
        coordination_attested_refs=frozenset({"YOK-B"}),
        serial_linked_refs=frozenset({"YOK-B"}),
    )
    verdict = evaluate_admission(_candidate(targets=(21,)), context)
    assert not verdict.admit
    assert verdict.reason == REFUSE_SERIAL_ORDERING


def test_second_migration_carrier_refuses():
    context = TrainContext(members=(
        _candidate("YOK-B", carrier=True),
        _candidate("YOK-C"),
    ))
    verdict = evaluate_admission(_candidate(carrier=True), context)
    assert not verdict.admit
    assert verdict.reason == REFUSE_MIGRATION_CARRIER
    assert verdict.conflicting_members == ("YOK-B",)


def test_non_carrier_joins_carrier_train():
    context = TrainContext(members=(_candidate("YOK-B", carrier=True),))
    verdict = evaluate_admission(_candidate(), context)
    assert verdict.admit
