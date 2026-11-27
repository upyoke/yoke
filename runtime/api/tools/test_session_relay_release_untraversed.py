"""Relay install never follows its own release or launch links.

A native Windows SSH session may refuse to traverse a directory junction its
user made (WinError 448, untrusted mount point). The guard below refuses every
stat, open and resolve that follows a link under the relay state directory, so
these tests fail wherever setup reads through the ``release`` or ``venv``
pointer instead of reading the target the pointer records.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from runtime.api.tools.session_relay_release_test_support import (
    NEXT_RELEASE,
    RELEASE,
    fake_venv,
    relay_instance,
    runner_for,
)
from yoke_contracts import platform_links as links
from yoke_core.tools import session_relay_release as release
from yoke_core.tools.session_relay_release_install import (
    converge_relay_launcher,
    pin_relay_release,
)

pytestmark = pytest.mark.windows

UNTRUSTED = "untrusted mount point (WinError 448)"


def _refuse_link_traversal(monkeypatch, root: Path) -> None:
    root = Path(os.path.abspath(root))

    def crosses(path, follow: bool = True) -> bool:
        if isinstance(path, int):
            return False
        selected = Path(os.path.abspath(os.fspath(path)))
        if not selected.is_relative_to(root):
            return False
        steps = list(reversed(selected.parents)) + ([selected] if follow else [])
        return any(step.is_relative_to(root) and links.is_link(step) for step in steps)

    def refuse(path):
        raise OSError(22, UNTRUSTED, os.fspath(path))

    original_stat, original_open = os.stat, io.open
    original_realpath, original_resolve = os.path.realpath, Path.resolve

    def stat(path, *args, follow_symlinks=True, **kwargs):
        if crosses(path, follow_symlinks):
            refuse(path)
        return original_stat(path, *args, follow_symlinks=follow_symlinks, **kwargs)

    def open_(file, *args, **kwargs):
        if crosses(file):
            refuse(file)
        return original_open(file, *args, **kwargs)

    def realpath(path, *args, **kwargs):
        if crosses(path):
            refuse(path)
        return original_realpath(path, *args, **kwargs)

    def resolve(self, *args, **kwargs):
        if crosses(self):
            refuse(self)
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    monkeypatch.setattr(io, "open", open_)
    monkeypatch.setattr(os.path, "realpath", realpath)
    monkeypatch.setattr(Path, "resolve", resolve)


def _pin(instance, version):
    return pin_relay_release(
        instance=instance,
        served_build=version,
        create_venv=fake_venv,
        runner=runner_for(version, []),
    )


def test_first_install_and_upgrade_never_follow_the_release_link(tmp_path, monkeypatch):
    instance = relay_instance(tmp_path)
    _refuse_link_traversal(monkeypatch, instance.state_dir)

    first = _pin(instance, RELEASE)
    active = instance.state_dir / "release"
    assert first.current and links.is_link(active)
    first_root = links.link_target(active)

    second = _pin(instance, NEXT_RELEASE)

    assert second.current and second.pinned_release == NEXT_RELEASE
    current_root = links.link_target(active)
    assert current_root != first_root
    receipt = json.loads((current_root / ".yoke-relay-release.json").read_text(encoding="utf-8"))
    assert receipt["previous_release"] == str(first_root)
    assert release.relay_release_receipt(instance.state_dir)["pinned_release"] == NEXT_RELEASE


def test_status_and_launcher_read_the_recorded_targets(tmp_path, monkeypatch):
    instance = relay_instance(tmp_path)
    _pin(instance, RELEASE)
    _refuse_link_traversal(monkeypatch, instance.state_dir)

    status = release.relay_release_status(
        instance=instance, refresh_served=False, runner=runner_for(RELEASE, [])
    )

    assert status.package_ready and status.pinned_release == RELEASE
    assert release.relay_launch_targets_runtime(instance.state_dir)
    assert release.relay_package_executable(instance.state_dir).is_file()
    launcher = converge_relay_launcher(instance, pin_release=lambda **_: None)
    assert launcher == release.relay_launch_executable(instance.state_dir)


def test_an_unreadable_release_link_refuses_with_its_recovery(tmp_path, monkeypatch):
    instance = relay_instance(tmp_path)
    _pin(instance, RELEASE)

    def denied(path):
        raise PermissionError(13, "Access is denied", os.fspath(path))

    monkeypatch.setattr(release, "relay_link_root", denied)

    with pytest.raises(release.RelayReleaseError) as refused:
        _pin(instance, NEXT_RELEASE)

    assert refused.value.code == release.RELAY_RELEASE_INSTALL_FAILED
    assert "Access is denied" in str(refused.value)
    assert "relay install" in str(refused.value)
