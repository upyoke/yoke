"""A turn may end on an item waiting at its workflow's release stage."""

from __future__ import annotations

import pytest

from yoke_core.domain import turn_end_unfinished_work as unfinished

LANDED_AT_RELEASE = {
    "item_id": 1,
    "status": "release",
    "merged_at": "2026-10-23T00:00:00Z",
    "workflow_id": "dash",
    "workflow_version": 10,
}


@pytest.mark.parametrize("waiting", [True, False])
def test_a_landed_item_at_release_wait_lets_the_turn_stop(monkeypatch, waiting):
    asked = []

    def at_release_wait(item, status):
        asked.append((item, status))
        return waiting

    monkeypatch.setattr(unfinished, "at_release_wait", at_release_wait)

    assert unfinished.stop_is_legitimate(LANDED_AT_RELEASE) is waiting
    assert asked == [({"workflow": {"id": "dash", "version": 10}}, "release")]
