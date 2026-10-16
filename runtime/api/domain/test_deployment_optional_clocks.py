"""Optional clocks preserve absence and required clocks remain strict."""

from types import SimpleNamespace
from dataclasses import replace

import pytest

from runtime.api.domain.test_deployment_composition_clock_filters import (
    DRIVER_STAMP,
    clocks as clocks,
)
from runtime.api.domain.test_deployment_clock_reads import (
    native_clocks as native_clocks,
)
from yoke_contracts.timestamps import InvalidInstant, format_instant
from yoke_core.domain import merge_queue_landing_marker as marker
from yoke_core.domain import merge_queue_landing_outcome as outcome
from yoke_core.domain import merge_queue_landing_pending as pending

ITEM_ID = 1
ITEM_REF = f"ITEM-{ITEM_ID}"


@pytest.mark.parametrize("field", ["observed_at", "changed_at"])
def test_required_observation_null_refuses_before_storage(field):
    from runtime.api.domain.test_merge_queue_landing_record import _record
    from yoke_core.domain.merge_queue_landing_record import write_landing_record
    from yoke_core.domain.merge_queue_landing_record_state import PENDING

    record = replace(
        _record(PENDING, DRIVER_STAMP, narrative="Required clock"), **{field: None}
    )
    with pytest.raises(InvalidInstant):
        write_landing_record(object(), record)


def test_absent_optional_queue_clocks_close_out_from_commit_evidence(
    native_clocks, monkeypatch
):
    from yoke_core.domain import item_landings_close_out as closeout
    from yoke_core.domain import standalone_item_merge_evidence as evidence

    native_clocks.execute(
        "UPDATE items SET merged_at=NULL, merge_queue_pr_number='42', merge_queue_enqueued_at=NULL, merge_queue_landed_at=NULL, merge_queue_notified_at=NULL WHERE id=1"
    )
    row = marker.read_landing_marker(native_clocks, 1)
    assert row == dict(
        pr_number="42", enqueued_at=None, landed_at=None, notified_at=None
    )
    monkeypatch.setattr(
        evidence,
        "call_dispatcher",
        lambda **_: SimpleNamespace(success=True, result={"fields": {"merged_at": ""}}),
    )
    assert evidence._merged_at(ITEM_REF) is None
    queue_stamp = native_clocks.execute(
        "SELECT merge_queue_landed_at FROM items WHERE id=1"
    ).fetchone()[0]
    monkeypatch.setattr(closeout.git, "commit_time", lambda *_: DRIVER_STAMP)
    sent = []
    monkeypatch.setattr(
        closeout,
        "call_dispatcher",
        lambda **kw: sent.append(kw) or SimpleNamespace(success=True),
    )
    _, note = closeout.close_out_lane(
        item_id=ITEM_REF,
        branch="feature",
        target="main",
        repo_root="/repo",
        outcome=SimpleNamespace(
            commit_sha="a" * 40, merge_sha="b" * 40, touched_files=()
        ),
        queue_pr_number="42",
        queue_landed_at=queue_stamp,
    )
    assert note == "" and sent[0]["payload"]["landed_at"] == format_instant(
        DRIVER_STAMP
    )
    with pytest.raises(InvalidInstant):
        closeout.landing_time(
            repo_root="/repo",
            merge_sha="b" * 40,
            queue_landed_at="2026-10-10 23:07:54.69593+00",
        )
    assert (
        native_clocks.execute(
            "SELECT merge_queue_landed_at FROM items WHERE id=1"
        ).fetchone()[0]
        is None
    )


def test_empty_optional_receipt_and_arming_clock_are_absent():
    writes = []

    def dispatch(*, function_id, payload=None, **_):
        if function_id == "items.detail.get":
            return SimpleNamespace(
                success=True,
                result={
                    "item": {
                        "merge_queue": {
                            "pr_number": "42",
                            "landed_at": "",
                            "enqueued_at": "",
                        }
                    }
                },
            )
        writes.append(payload)
        return SimpleNamespace(
            success=True, result={"enqueued_at": payload["enqueued_at"]}
        )

    assert outcome.recorded_landing(dispatch, ITEM_REF) == ("42", None)
    stamp, warning = pending.mark_landing_pending(
        ITEM_REF, "42", dispatch=dispatch, now=DRIVER_STAMP, preserve_existing=True
    )
    assert stamp == DRIVER_STAMP and warning == ""
    assert writes[0]["enqueued_at"] == format_instant(DRIVER_STAMP)


def test_observer_discovers_and_stamps_absent_optional_clocks(
    native_clocks, monkeypatch
):
    from runtime.api.domain.merge_queue_observer_test_helpers import merged
    from yoke_core.domain import merge_queue_landing_observer as observer

    native_clocks.execute(
        "ALTER TABLE projects ADD public_item_prefix text DEFAULT 'ITEM', ADD default_branch text DEFAULT 'main'"
    )
    native_clocks.execute(
        "ALTER TABLE items ADD project_sequence integer DEFAULT 1, ADD status text DEFAULT 'implementing'"
    )
    native_clocks.execute(
        "UPDATE items SET merge_queue_pr_number='42',merge_queue_enqueued_at=NULL,merge_queue_landed_at=NULL,merge_queue_notified_at=NULL WHERE id=1"
    )
    monkeypatch.setattr(observer, "push_notice", lambda *_, **__: "delivered")
    result = observer.observe_pending_landings(
        native_clocks, [1], now=DRIVER_STAMP, read_state=merged
    )
    assert result["checked"] == result["landed"] == result["notified"] == 1
    assert not result.get("notice_errors")
    clocks = marker.read_landing_marker(native_clocks, 1)
    assert clocks["landed_at"] is not None and clocks["notified_at"] == DRIVER_STAMP
