"""Close-out semantics resolve on the connection, not on the local build.

The standalone merge switches to the same-universe local Postgres
connection so it can lock merge admission. Under that switch every
control-plane call dispatches in-process, so the item's evidence contract
is decided by whatever engine this process imported rather than by the
build the fleet serves. These tests pin the two steps that carry terminal
semantics back onto the connection the operator selected, and pin the
merge's own steps to the admission override they need.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_core.domain import close_out_control_plane_authority as close_out
from yoke_core.domain import standalone_item_merge_evidence as merge_evidence
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge_terminal as terminal

CONNECTED = "prod"
ADMISSION = "prod-db-admin"
LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40
LANE = landed.LandedLane(
    branch="ITEM-1",
    target="main",
    commit_sha=LANE_SHA,
    merge_sha=MERGE_SHA,
    touched_files=("a.py",),
    source="lane branch",
)
OUTCOME = SimpleNamespace(
    commit_sha=LANE_SHA,
    merge_sha=MERGE_SHA,
    touched_files=("a.py",),
)


def _under_admission_override(monkeypatch) -> None:
    monkeypatch.setitem(os.environ, ENV_OVERRIDE, ADMISSION)


def _record_selected_env(monkeypatch, seen: list) -> None:
    def record(**_kwargs) -> str:
        seen.append(os.environ.get(ENV_OVERRIDE, ""))
        return ""

    monkeypatch.setattr(merge_evidence, "record", record)


def test_evidence_write_dispatches_on_the_connected_control_plane(monkeypatch):
    _under_admission_override(monkeypatch)
    seen: list = []
    _record_selected_env(monkeypatch, seen)

    with close_out.bind_connected_control_plane(CONNECTED):
        refusal, warning = close_out.record_execution_evidence(
            item_id=7,
            outcome=OUTCOME,
            result_summary="Landed the standalone change.",
            verification_summary="Registered verification passed.",
            verification_status="passed",
            no_changes=False,
            tree_root="/repo/.worktrees/lane",
        )

    assert (refusal, warning) == ("", "")
    assert seen == [CONNECTED]
    # The merge's own steps keep the admission connection they need.
    assert os.environ[ENV_OVERRIDE] == ADMISSION


def test_terminal_transition_dispatches_on_the_connected_control_plane(
    monkeypatch,
):
    _under_admission_override(monkeypatch)
    seen: list = []

    def transition(**_kwargs) -> str:
        seen.append(os.environ.get(ENV_OVERRIDE, ""))
        return ""

    monkeypatch.setattr(terminal, "transition_to_done", transition)

    with close_out.bind_connected_control_plane(CONNECTED):
        assert (
            close_out.transition_to_done(
                item_id=7,
                source_status="reviewing-implementation",
                repo_root="/repo",
                lane=LANE,
            )
            == ""
        )

    assert seen == [CONNECTED]
    assert os.environ[ENV_OVERRIDE] == ADMISSION


def test_an_unbound_caller_keeps_its_own_connection(monkeypatch):
    """A direct engine call names no connected plane, so nothing switches."""
    _under_admission_override(monkeypatch)
    seen: list = []
    _record_selected_env(monkeypatch, seen)

    refusal, warning = close_out.record_execution_evidence(
        item_id=7,
        outcome=OUTCOME,
        result_summary="Landed the standalone change.",
        verification_summary="Registered verification passed.",
        verification_status="passed",
        no_changes=False,
        tree_root="/repo/.worktrees/lane",
    )

    assert (refusal, warning) == ("", "")
    assert seen == [ADMISSION]
    assert close_out.bound_connected_env() is None


def test_a_refused_write_whose_record_landed_warns_instead_of_failing(
    monkeypatch,
):
    """A relayed write that succeeds on retry still reports the failed try."""
    _under_admission_override(monkeypatch)
    monkeypatch.setattr(
        merge_evidence, "record", lambda **_kwargs: "relay timed out"
    )
    monkeypatch.setattr(
        merge_evidence,
        "recorded_covers_merge",
        lambda item_id, merge_sha: merge_sha == MERGE_SHA,
    )

    with close_out.bind_connected_control_plane(CONNECTED):
        refusal, warning = close_out.record_execution_evidence(
            item_id=7,
            outcome=OUTCOME,
            result_summary="Landed the standalone change.",
            verification_summary="Registered verification passed.",
            verification_status="passed",
            no_changes=False,
            tree_root="/repo/.worktrees/lane",
        )

    assert refusal == ""
    assert "relay timed out" in warning


def test_a_refused_write_with_no_record_fails_the_close_out(monkeypatch):
    _under_admission_override(monkeypatch)
    monkeypatch.setattr(
        merge_evidence, "record", lambda **_kwargs: "evidence refused"
    )
    monkeypatch.setattr(
        merge_evidence, "recorded_covers_merge", lambda *_args: False
    )

    with close_out.bind_connected_control_plane(CONNECTED):
        refusal, warning = close_out.record_execution_evidence(
            item_id=7,
            outcome=OUTCOME,
            result_summary="Landed the standalone change.",
            verification_summary="Registered verification passed.",
            verification_status="passed",
            no_changes=False,
            tree_root="/repo/.worktrees/lane",
        )

    assert refusal == "evidence refused"
    assert warning == ""
