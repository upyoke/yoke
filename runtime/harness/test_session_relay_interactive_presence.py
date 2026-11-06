"""A spent launch cannot testify that a live interactive holder is gone."""

import pytest

from runtime.harness.test_session_relay_process_liveness import (
    DEAD_SESSION,
    RECORDED_START,
    _anchor,
    _handle,
    _start_time_of,
)
from yoke_harness.session_relay_process_liveness import verified_dead_sessions


@pytest.mark.parametrize(
    "anchor_start,live", [(RECORDED_START, True), ("reused", False), (None, False)]
)
def test_contended_interactive_holder_prevents_false_death(
    tmp_path, monkeypatch, anchor_start, live
):
    monkeypatch.setattr("os.getpgid", lambda pid: 99)
    _handle(DEAD_SESSION, 4002, "spent-launch")
    anchors = tmp_path / "anchors"
    _anchor(
        anchors,
        "another-session",
        4004,
        anchor_start_time=anchor_start,
        shared_by_multiple_sessions=True,
        contending_session_ids=[DEAD_SESSION],
    )
    deaths = verified_dead_sessions(
        state_dir=tmp_path, anchors_dir=anchors, start_time_of=_start_time_of({4004})
    )
    assert [death.session_id for death in deaths] == ([] if live else [DEAD_SESSION])
