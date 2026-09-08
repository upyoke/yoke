"""One poll's records reach a server that caps how many a request may carry.

An over-long collection fails the request as a whole rather than being
trimmed, so a machine holding more records than the cap used to deliver none
of them, every poll. Each case here validates the dispatched payload against
the real request model: a count alone would pass while the control plane
still rejected the request and heard nothing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from yoke_contracts.session_control.relay_models import (
    RELAY_REPORT_COLLECTION_LIMIT,
    RelayLivenessRequest,
)
from yoke_contracts.session_identity import ANCHORS_DIR_NAME
from yoke_harness.session_launch_containment import (
    record_supervised_native,
    supervision_record_path,
)
from yoke_harness.session_launch_handles import native_handle_path
from yoke_harness.session_relay_launch_settlement import (
    report_unregistered_launch_deaths,
)
from yoke_harness.session_relay_process_liveness import report_verified_dead_sessions


OVERFLOW = RELAY_REPORT_COLLECTION_LIMIT + 10
RECORDED_START = "Mon Aug 24 08:00:00 2026"


class _Inventory:
    relay_id = "machine:test"
    machine_id = "machine-1"
    project_ids = (1,)


class _Response:
    def __init__(self, success: bool, result: dict[str, Any] | None = None) -> None:
        self.success = success
        self.result = result
        self.error = None


class _BatchDispatcher:
    """Answer each request the way the server does, for what it was sent."""

    def __init__(self, *, collection: str, refuse_call: int | None = None) -> None:
        self.batches: list[tuple[str, ...]] = []
        self._collection = collection
        self._refuse_call = refuse_call

    def __call__(self, *, function_id: str, target: Any, payload: Any, timeout_s: int):
        del function_id, target, timeout_s
        request = RelayLivenessRequest.model_validate(payload)
        sent = tuple(
            report.session_id if self._collection == "sessions" else report.launch_id
            for report in getattr(request, self._collection)
        )
        self.batches.append(sent)
        if len(self.batches) == self._refuse_call:
            return _Response(False)
        return _Response(
            True,
            {"ended": list(sent), "skipped": [], "closed_launches": list(sent)},
        )


def _gone(_pid: int) -> str:
    """No recorded pid is still the recorded process."""
    return "some-other-start"


def _dead_handles(count: int) -> tuple[str, ...]:
    """Record more gone sessions than one request is allowed to carry."""
    sessions = tuple(
        f"{index:08d}-2222-4222-8222-222222222222" for index in range(count)
    )
    for index, session_id in enumerate(sessions):
        path = native_handle_path(f"launch-{index:04d}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "launch_id": f"launch-{index:04d}",
                    "target_session_id": session_id,
                    "pid": 5000 + index,
                    "process_start_time": RECORDED_START,
                }
            ),
            encoding="utf-8",
        )
    return sessions


def _dead_launches(state_dir: Path, count: int) -> tuple[str, ...]:
    """Supervise more gone natives than one request is allowed to carry."""
    launches = tuple(
        f"{index:08d}-3333-4333-8333-333333333333" for index in range(count)
    )
    for index, launch_id in enumerate(launches):
        # A record exists only for a pid that exists, so each names this
        # process; the caller's start-time lookup is what makes them gone.
        record_supervised_native(
            launch_id,
            os.getpid(),
            native_session_id=f"native-{index}",
            state_dir=state_dir,
        )
    return launches


def test_more_dead_sessions_than_one_request_holds_are_sent_as_accepted_batches(
    tmp_path: Path,
) -> None:
    anchors = tmp_path / ANCHORS_DIR_NAME
    anchors.mkdir(parents=True, exist_ok=True)
    sessions = _dead_handles(OVERFLOW)
    dispatcher = _BatchDispatcher(collection="sessions")

    ended = report_verified_dead_sessions(
        dispatcher,
        _Inventory(),
        state_dir=tmp_path,
        anchors_dir=anchors,
        start_time_of=_gone,
    )

    assert [len(batch) for batch in dispatcher.batches] == [
        RELAY_REPORT_COLLECTION_LIMIT,
        10,
    ]
    assert sorted(ended) == sorted(sessions), "every death is reported, none dropped"
    assert not any(
        native_handle_path(f"launch-{index:04d}").exists() for index in range(OVERFLOW)
    )


def test_a_refused_session_batch_keeps_its_records_and_the_ones_behind_it(
    tmp_path: Path,
) -> None:
    """The undelivered tail is read again next poll rather than spent here."""
    anchors = tmp_path / ANCHORS_DIR_NAME
    anchors.mkdir(parents=True, exist_ok=True)
    sessions = _dead_handles(OVERFLOW)
    dispatcher = _BatchDispatcher(collection="sessions", refuse_call=2)

    ended = report_verified_dead_sessions(
        dispatcher,
        _Inventory(),
        state_dir=tmp_path,
        anchors_dir=anchors,
        start_time_of=_gone,
    )

    assert sorted(ended) == sorted(sessions[:RELAY_REPORT_COLLECTION_LIMIT])
    assert len(dispatcher.batches) == 2, "a refusal ends this poll's delivery"
    assert not any(
        native_handle_path(f"launch-{index:04d}").exists()
        for index in range(RELAY_REPORT_COLLECTION_LIMIT)
    )
    assert all(
        native_handle_path(f"launch-{index:04d}").exists()
        for index in range(RELAY_REPORT_COLLECTION_LIMIT, OVERFLOW)
    )


def test_more_launch_deaths_than_one_request_holds_are_sent_as_accepted_batches(
    tmp_path: Path,
) -> None:
    launches = _dead_launches(tmp_path, OVERFLOW)
    dispatcher = _BatchDispatcher(collection="launches")

    reported = report_unregistered_launch_deaths(
        dispatcher,
        _Inventory(),
        state_dir=tmp_path,
        start_time_of=_gone,
    )

    assert [len(batch) for batch in dispatcher.batches] == [
        RELAY_REPORT_COLLECTION_LIMIT,
        10,
    ]
    assert sorted(reported) == sorted(launches), "every death is reported, none dropped"
    assert not any(
        supervision_record_path(launch_id, tmp_path).exists() for launch_id in launches
    )


def test_a_refused_launch_batch_keeps_its_records_and_the_ones_behind_it(
    tmp_path: Path,
) -> None:
    """A custody record is released only for a batch the server received."""
    launches = _dead_launches(tmp_path, OVERFLOW)
    dispatcher = _BatchDispatcher(collection="launches", refuse_call=2)

    reported = report_unregistered_launch_deaths(
        dispatcher,
        _Inventory(),
        state_dir=tmp_path,
        start_time_of=_gone,
    )

    landed = launches[:RELAY_REPORT_COLLECTION_LIMIT]
    assert sorted(reported) == sorted(landed)
    assert len(dispatcher.batches) == 2, "a refusal ends this poll's delivery"
    assert not any(
        supervision_record_path(launch_id, tmp_path).exists() for launch_id in landed
    )
    assert all(
        supervision_record_path(launch_id, tmp_path).exists()
        for launch_id in launches[RELAY_REPORT_COLLECTION_LIMIT:]
    )
