"""Every merge outcome is recorded on the item before it is ever emitted.

Both merge paths — the standalone item boundary and the epic lane engine —
run through one emit function, so that function is where the durable half
belongs. Telemetry is emitted beside it and is free to fail.
"""

from __future__ import annotations

import pytest

from yoke_core.engines import merge_worktree_events as events

ITEM_ID = 41
BRANCH = "ITEM-1"
TARGET = "main"


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    """Capture receipt writes; telemetry emission is not the subject here."""
    from yoke_core.domain import item_merge_receipts as receipts

    calls: list[tuple[str, dict]] = []

    def record_failure(item_id, **kwargs):
        calls.append(("failure", {"item_id": item_id, **kwargs}))
        return ""

    def record_settlement(item_id, **kwargs):
        calls.append(("settlement", {"item_id": item_id, **kwargs}))
        return ""

    monkeypatch.setattr(receipts, "record_failure", record_failure)
    monkeypatch.setattr(receipts, "record_settlement", record_settlement)
    monkeypatch.setattr(events, "_emit_telemetry", lambda *a, **k: None)
    return calls


@pytest.fixture
def printed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    lines: list[str] = []
    monkeypatch.setattr(
        events, "_print", lambda msg, err=False: lines.append(str(msg)),
    )
    return lines


def _context(**extra) -> dict:
    return {"branch": BRANCH, "target": TARGET, **extra}


def test_a_push_failure_records_its_phase_and_reason(recorded) -> None:
    events._emit_merge_event(
        "MergeBranchPushFailed",
        severity="ERROR",
        outcome="failure",
        item_id=ITEM_ID,
        context=_context(phase="branch-push", stderr="remote rejected"),
    )

    kind, call = recorded[0]
    assert kind == "failure"
    assert call["item_id"] == ITEM_ID
    assert call["branch"] == BRANCH
    assert call["target"] == TARGET
    assert call["label"] == "merge failed"
    assert call["phase"] == "branch-push"
    assert call["reason"] == "remote rejected"


def test_a_ci_failure_records_the_label_the_stage_strip_shows(recorded) -> None:
    events._emit_merge_event(
        "MergePullRequestCiFailed",
        severity="ERROR",
        outcome="failure",
        item_id=ITEM_ID,
        context=_context(phase="pr-checks-poll", stderr="1 check failing"),
    )

    assert recorded[0][1]["label"] == "CI checks failed"


def test_a_missing_verification_refusal_records_its_own_label(recorded) -> None:
    events._emit_merge_event(
        "MergeBlockedNoVerificationEvidence",
        severity="ERROR",
        outcome="failure",
        item_id=ITEM_ID,
        context=_context(),
    )

    assert recorded[0][1]["label"] == "verification missing"


def test_a_successful_engine_run_settles_the_identity(recorded) -> None:
    events._emit_merge_event(
        "MergeEngineSucceeded",
        outcome="success",
        item_id=ITEM_ID,
        context=_context(epic_id=None),
    )

    kind, call = recorded[0]
    assert kind == "settlement"
    assert call == {"item_id": ITEM_ID, "branch": BRANCH, "target": TARGET}


def test_an_exit_code_stands_in_when_no_detail_was_captured(recorded) -> None:
    events._emit_merge_event(
        "MergeEngineFailed",
        severity="ERROR",
        outcome="failure",
        item_id=ITEM_ID,
        context=_context(exit_code=5),
    )

    assert recorded[0][1]["reason"] == "exit 5"


@pytest.mark.parametrize(
    ("event_name", "item_id", "context"),
    (
        ("MergeBranchPushed", ITEM_ID, {"branch": BRANCH, "target": TARGET}),
        ("MergeEngineFailed", None, {"branch": BRANCH, "target": TARGET}),
        ("MergeEngineFailed", ITEM_ID, {"target": TARGET}),
        ("MergeEngineFailed", ITEM_ID, None),
    ),
    ids=["not-an-outcome", "no-item", "no-branch", "no-context"],
)
def test_nothing_is_recorded_without_an_outcome_and_an_identity(
    recorded, event_name: str, item_id, context,
) -> None:
    events._emit_merge_event(
        event_name, item_id=item_id, context=context,
    )

    assert recorded == []


def test_a_refused_receipt_write_is_reported_and_never_unwinds_the_merge(
    monkeypatch: pytest.MonkeyPatch, printed: list[str],
) -> None:
    """Losing the strip's colour is smaller than losing the merge."""
    from yoke_core.domain import item_merge_receipts as receipts

    monkeypatch.setattr(
        receipts,
        "record_failure",
        lambda *_a, **_k: "merge receipt not recorded: control plane unreachable",
    )
    monkeypatch.setattr(events, "_emit_telemetry", lambda *a, **k: None)

    events._emit_merge_event(
        "MergeEngineFailed",
        severity="ERROR",
        outcome="failure",
        item_id=ITEM_ID,
        context=_context(exit_code=1),
    )

    assert any("control plane unreachable" in line for line in printed)
