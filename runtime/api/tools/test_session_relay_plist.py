"""Launchd convergence tests for the fresh-process machine relay."""

from __future__ import annotations

import os
from pathlib import Path
import plistlib
import subprocess

from yoke_contracts.organization_contract.fleet_keys import FLEET_KEY_SPECS
from yoke_core.tools.session_relay_plist import (
    RELAY_LAUNCHD_LABEL,
    RELAY_START_INTERVAL_SECONDS,
    install_relay_launchd,
    relay_launchd_paths,
    relay_plist_document,
    uninstall_relay_launchd,
)


def test_plist_runs_canonical_yoke_once_without_keepalive(tmp_path: Path) -> None:
    paths = relay_launchd_paths(home=tmp_path, yoke_home=tmp_path / ".yoke")
    executable = tmp_path / "bin" / "yoke"
    document = relay_plist_document(executable=executable, paths=paths)

    assert document["ProgramArguments"] == [
        str(executable),
        "relay",
        "serve-once",
    ]
    policy_minimum = FLEET_KEY_SPECS["fleet.relay_poll_seconds"].minimum
    assert document["StartInterval"] == RELAY_START_INTERVAL_SECONDS == policy_minimum
    assert document["RunAtLoad"] is True
    assert "KeepAlive" not in document
    assert str(paths.stdout_log).startswith(str(tmp_path / ".yoke" / "relay"))


def test_plist_preserves_only_native_cli_search_directories(tmp_path: Path) -> None:
    paths = relay_launchd_paths(home=tmp_path, yoke_home=tmp_path / ".yoke")
    executable = tmp_path / "bin" / "yoke"
    vendor_bin = tmp_path / "vendor" / "bin"
    vendor_bin.mkdir(parents=True)
    for name in ("claude", "codex", "cursor-agent"):
        command = vendor_bin / name
        command.touch(mode=0o755)
    document = relay_plist_document(
        executable=executable,
        paths=paths,
        environ={"PATH": str(vendor_bin)},
    )

    search = document["EnvironmentVariables"]["PATH"].split(os.pathsep)
    assert search[:2] == [str(executable.parent), str(vendor_bin)]
    assert search.count(str(vendor_bin)) == 1


def test_install_bootstraps_and_uninstall_boots_out_then_deletes(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "bin" / "yoke"
    executable.parent.mkdir()
    executable.touch()
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    installed = install_relay_launchd(
        home=tmp_path,
        yoke_home=tmp_path / ".yoke",
        executable=executable,
        runner=runner,
        platform="darwin",
        uid=501,
    )

    assert installed.loaded and installed.plist_current
    with installed.plist_path.open("rb") as handle:
        document = plistlib.load(handle)
    assert document["Label"] == RELAY_LAUNCHD_LABEL
    assert calls[0][:2] == ["launchctl", "bootout"]
    assert calls[1][:2] == ["launchctl", "bootstrap"]
    assert calls[2][:2] == ["launchctl", "print"]

    removed = uninstall_relay_launchd(
        home=tmp_path,
        yoke_home=tmp_path / ".yoke",
        runner=runner,
        platform="darwin",
        uid=501,
    )
    assert not removed.plist_present
    assert not installed.plist_path.exists()
    assert calls[3][:2] == ["launchctl", "bootout"]
