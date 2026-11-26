"""The relay detects publication only in a stable-launcher child."""

import sys

import pytest

from yoke_cli.config import cli_release_resident as resident


@pytest.mark.parametrize("layout", ["bin/python3", "Scripts/python.exe"])
def test_running_release_superseded_tracks_current(tmp_path, monkeypatch, layout):
    old, new = tmp_path / "releases/a", tmp_path / "releases/b"
    for generation in (old, new):
        (generation / "tools/yoke-cli" / layout).parent.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(old / "tools/yoke-cli" / layout))
    monkeypatch.setattr(sys, "_yoke_stable_launcher", True, raising=False)
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

    monkeypatch.delattr(sys, "_yoke_stable_launcher")
    assert not resident.running_release_superseded()


def test_launcher_child_outside_release_does_not_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "venv/bin/python"))
    monkeypatch.setattr(sys, "_yoke_stable_launcher", True, raising=False)
    assert not resident.running_release_superseded()


def test_current_launcher_child_retries_retirement_after_leases_clear(
    tmp_path, monkeypatch
):
    runtime = resident.runtime
    root = tmp_path / "cli"
    releases = root / "releases"
    old, current, pending, in_use = (
        releases / name for name in ("old", "current", "pending", "in-use")
    )
    for generation in (old, current, pending, in_use):
        generation.mkdir(parents=True)
        (generation / "lease").touch()
    (pending / "pending").touch()
    pointer = root / "current"
    pointer.write_text("current\n", encoding="utf-8")
    interpreter = current / "tools/yoke-cli/Scripts/python.exe"
    interpreter.parent.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(interpreter))
    monkeypatch.setattr(sys, "_yoke_stable_launcher", True, raising=False)
    publication_lock = root / "publication.lock"

    with runtime._lease(in_use):
        with runtime._lease(old), runtime._lease(pending), runtime.locked(publication_lock):
            runtime.collect(root, pending_safe=True)
            assert old.is_dir()
        with runtime.locked(publication_lock):
            resident.collect_superseded_releases()
            assert old.is_dir()

        resident.collect_superseded_releases()

        assert not old.exists()
        assert current.is_dir()
        assert pending.is_dir()
        assert in_use.is_dir()
        assert list((root / "retired").iterdir()) == []
    assert pointer.read_text(encoding="utf-8") == "current\n"
