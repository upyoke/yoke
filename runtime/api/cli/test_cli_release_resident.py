"""The relay detects publication only in a stable-launcher child."""

import sys

import pytest

from yoke_cli.config import cli_release_resident as resident
from yoke_cli.config import cli_release_runtime as runtime


@pytest.mark.parametrize("layout", ["bin/python3", "Scripts/python.exe"])
def test_running_release_superseded_tracks_current(tmp_path, monkeypatch, layout):
    old, new = tmp_path / "releases/a", tmp_path / "releases/b"
    for generation in (old, new):
        (generation / "tools/yoke-cli" / layout).parent.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(old / "tools/yoke-cli" / layout))
    monkeypatch.setattr(runtime, "STARTED_BY_LAUNCHER", True)
    current = tmp_path / "current"

    assert not resident.running_release_superseded()
    current.write_bytes(b"\xff")
    assert not resident.running_release_superseded()
    current.write_text("..\n", encoding="utf-8")
    assert not resident.running_release_superseded()
    current.write_text("a\n", encoding="utf-8")
    assert not resident.running_release_superseded()
    current.write_text("b\n", encoding="utf-8")
    assert resident.running_release_superseded()

    monkeypatch.setattr(runtime, "STARTED_BY_LAUNCHER", False)
    assert not resident.running_release_superseded()


def test_launcher_child_outside_release_does_not_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "venv/bin/python"))
    monkeypatch.setattr(runtime, "STARTED_BY_LAUNCHER", True)
    assert not resident.running_release_superseded()
