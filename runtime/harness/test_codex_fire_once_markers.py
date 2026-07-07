"""Codex hook fire-once marker coverage."""

from __future__ import annotations

from runtime.harness.codex import codex_hooks_payload as payload


def test_check_and_arm_marker_is_fire_once(tmp_path):
    marker = tmp_path / "marker"

    assert payload.check_and_arm_marker(str(marker)) is True
    assert payload.check_and_arm_marker(str(marker)) is False


def test_check_and_arm_marker_uses_exclusive_create(monkeypatch, tmp_path):
    seen = {}

    def fake_open(path, flags, mode):  # noqa: ARG001
        seen["flags"] = flags
        raise FileExistsError

    monkeypatch.setattr(payload.os, "open", fake_open)

    assert payload.check_and_arm_marker(str(tmp_path / "marker")) is False
    assert seen["flags"] & payload.os.O_EXCL
