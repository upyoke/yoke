"""Status lists surface marks only when a control plane is already reachable."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_cli.config.status_surface_policy import attach_live_marks


def test_attach_live_marks_skips_dispatcher_when_plane_is_unreachable(
    tmp_path: Path, monkeypatch,
) -> None:
    config = tmp_path / "config.json"
    machine = "00000000-0000-4000-8000-000000000099"
    config.write_text(json.dumps({"machine_id": machine}), encoding="utf-8")
    called = {"n": 0}

    def _fail(*_args, **_kwargs):
        called["n"] += 1
        raise AssertionError("status must not relay list against an inert plane")

    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        _fail,
    )
    report = attach_live_marks(
        {"server": {"reachable": False}, "db": {"relevant": False, "ok": False}},
        config,
    )
    assert called["n"] == 0
    assert report["surface_policies"] == {"machine_id": machine, "marks": []}
