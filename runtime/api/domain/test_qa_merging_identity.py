"""Merge identity keeps the PR-entry SHA when a queue batch is recorded later."""

from yoke_core.domain.qa_merging_identity import (
    accepted_merging_shas,
    ci_run_identity_shas,
    queue_batch_covers_receipt,
)
from yoke_core.domain.qa_terminal_settlement import blocking_requirement_issues

LANE = "a" * 40
PR_ENTRY = "b" * 40
MERGE = "c" * 40
STALE = "d" * 40


def _ci_result(head: str, *, batch_merge: str = "") -> str:
    payload = '{"verification_tree": {"head_sha": "' + head + '"}}'
    if not batch_merge:
        return payload
    return (
        '{"verification_tree": {"head_sha": "' + head + '"}, '
        '"merge_queue_batch": {"combined_head_sha": "' + head + '", '
        '"merge_sha": "' + batch_merge + '"}}'
    )


def test_ci_identity_keeps_pr_entry_when_batch_is_newer():
    shas = ci_run_identity_shas(
        (
            _ci_result(MERGE, batch_merge=MERGE),
            _ci_result(PR_ENTRY),
        )
    )

    assert PR_ENTRY in shas
    assert MERGE in shas


def test_newest_batch_alone_does_not_drop_the_entry_head():
    """The previous single-newest read would have returned only MERGE."""
    shas = ci_run_identity_shas(
        (
            _ci_result(MERGE, batch_merge=MERGE),
            _ci_result(PR_ENTRY),
        )
    )

    assert shas[0] == PR_ENTRY


def test_batch_covers_when_train_merge_matches_the_receipt():
    assert queue_batch_covers_receipt(
        (_ci_result(MERGE, batch_merge=MERGE), _ci_result(PR_ENTRY)),
        (LANE, MERGE),
    )


def test_batch_does_not_cover_a_different_merge_identity():
    other = "e" * 40
    assert not queue_batch_covers_receipt(
        (_ci_result(other, batch_merge=other),),
        (LANE, MERGE),
    )


def test_passing_pr_entry_run_is_stale_against_lane_and_merge_only():
    issues = blocking_requirement_issues(
        [
            {
                "id": 7,
                "blocking_mode": "blocking",
                "run_id": 9,
                "verdict": "pass",
                "completed_at": "2026-08-25T00:00:00Z",
                "method_id": "command-ci",
                "recorded_head_sha": PR_ENTRY,
            }
        ],
        accepted_shas=(LANE, MERGE),
        public_ref="ITEM-1",
        require_any=True,
    )

    assert len(issues) == 1
    assert issues[0].state == "stale-sha"


def test_passing_pr_entry_run_is_covered_when_identity_includes_it():
    issues = blocking_requirement_issues(
        [
            {
                "id": 7,
                "blocking_mode": "blocking",
                "run_id": 9,
                "verdict": "pass",
                "completed_at": "2026-08-25T00:00:00Z",
                "method_id": "command-ci",
                "recorded_head_sha": PR_ENTRY,
            }
        ],
        accepted_shas=(LANE, PR_ENTRY, MERGE),
        public_ref="ITEM-1",
        require_any=True,
    )

    assert issues == []


def test_accepted_set_includes_blocking_head_when_batch_covers(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.qa_merging_identity._evidence_sha",
        lambda *_a: "",
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_merging_identity._receipt_shas",
        lambda *_a: [LANE, MERGE],
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_merging_identity._passing_ci_raw_results",
        lambda *_a: [
            _ci_result(MERGE, batch_merge=MERGE),
            _ci_result(PR_ENTRY),
        ],
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_merging_identity._lane_sha",
        lambda *_a: LANE,
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_merging_identity._passing_blocking_heads",
        lambda *_a: [PR_ENTRY],
    )

    accepted = accepted_merging_shas(object(), 42)

    assert accepted == (LANE, MERGE, PR_ENTRY)


def test_stale_blocking_head_stays_out_without_a_covering_batch(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.qa_merging_identity._evidence_sha",
        lambda *_a: "",
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_merging_identity._receipt_shas",
        lambda *_a: [LANE, MERGE],
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_merging_identity._passing_ci_raw_results",
        lambda *_a: [_ci_result(PR_ENTRY)],
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_merging_identity._lane_sha",
        lambda *_a: LANE,
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_merging_identity._passing_blocking_heads",
        lambda *_a: [STALE],
    )

    accepted = accepted_merging_shas(object(), 42)

    assert STALE not in accepted
    assert PR_ENTRY in accepted
    assert MERGE in accepted
    assert LANE in accepted
