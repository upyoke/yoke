"""Launchd convergence tests for the fresh-process machine relay."""

from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import subprocess

import pytest

from yoke_cli.config import machine_config
from yoke_cli.config.session_relay_instance import (
    RelayInstanceError,
    resolve_relay_instance,
)
from yoke_contracts.organization_contract.fleet_keys import FLEET_KEY_SPECS
from yoke_core.tools.session_relay_plist import (
    RELAY_LAUNCHD_LABEL,
    RELAY_START_INTERVAL_SECONDS,
    install_relay_launchd,
    relay_launchd_paths,
    relay_launchd_status,
    relay_plist_document,
    uninstall_relay_launchd,
)


def _config(tmp_path: Path) -> Path:
    path = tmp_path / ".yoke" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    connections = {}
    for environment, prod in (("prod", True), ("stage", False)):
        connections[environment] = {
            "transport": "https",
            "prod": prod,
            "api_url": f"https://{environment}.example.test",
            "credential_source": {
                "kind": "token_file",
                "path": f"~/.yoke/secrets/{environment}.token",
            },
        }
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod",
                "connections": connections,
                "projects": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _instance(tmp_path: Path, environment: str):
    return resolve_relay_instance(
        config_path=_config(tmp_path),
        environment=environment,
        yoke_home=tmp_path / ".yoke",
    )


def test_plist_runs_canonical_yoke_once_without_keepalive(tmp_path: Path) -> None:
    paths = relay_launchd_paths(home=tmp_path, instance=_instance(tmp_path, "prod"))
    executable = tmp_path / "bin" / "yoke"
    document = relay_plist_document(executable=executable, paths=paths)

    assert document["ProgramArguments"] == [
        str(executable),
        "--env",
        "prod",
        "relay",
        "serve-once",
    ]
    policy_minimum = FLEET_KEY_SPECS["fleet.relay_poll_seconds"].minimum
    assert document["StartInterval"] == RELAY_START_INTERVAL_SECONDS == policy_minimum
    assert document["RunAtLoad"] is True
    assert "KeepAlive" not in document
    assert str(paths.stdout_log).startswith(str(tmp_path / ".yoke" / "relay"))


def test_plist_preserves_only_native_cli_search_directories(tmp_path: Path) -> None:
    paths = relay_launchd_paths(home=tmp_path, instance=_instance(tmp_path, "prod"))
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
    config_path = _config(tmp_path)
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
        config_path=config_path,
        environment="prod",
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
        config_path=config_path,
        environment="prod",
        runner=runner,
        platform="darwin",
        uid=501,
    )
    assert not removed.plist_present
    assert not installed.plist_path.exists()
    assert calls[3][:2] == ["launchctl", "bootout"]


def test_prod_and_stage_have_isolated_labels_paths_and_pinned_commands(
    tmp_path: Path,
) -> None:
    config_path = _config(tmp_path)
    prod = resolve_relay_instance(
        config_path=config_path,
        environment="prod",
        yoke_home=tmp_path / ".yoke",
    )
    stage = resolve_relay_instance(
        config_path=config_path,
        environment="stage",
        yoke_home=tmp_path / ".yoke",
    )
    prod_paths = relay_launchd_paths(home=tmp_path, instance=prod)
    stage_paths = relay_launchd_paths(home=tmp_path, instance=stage)

    assert prod.label == RELAY_LAUNCHD_LABEL
    assert stage.label.startswith(f"{RELAY_LAUNCHD_LABEL}.")
    assert stage.label != prod.label
    assert stage_paths.plist != prod_paths.plist
    assert stage_paths.state_dir != prod_paths.state_dir
    assert stage_paths.stdout_log != prod_paths.stdout_log
    assert stage_paths.stderr_log != prod_paths.stderr_log

    document = relay_plist_document(
        executable=tmp_path / "bin" / "yoke",
        paths=stage_paths,
    )
    assert document["Label"] == stage.label
    assert document["ProgramArguments"] == [
        str(tmp_path / "bin" / "yoke"),
        "--env",
        "stage",
        "relay",
        "serve-once",
    ]
    assert document["EnvironmentVariables"][machine_config.CONFIG_FILE_ENV] == str(
        config_path.resolve()
    )
    assert "stage.token" not in repr(document)
    assert "stage.example.test" not in repr(document)


def test_stage_install_never_boots_out_prod_and_status_is_env_exact(
    tmp_path: Path,
) -> None:
    config_path = _config(tmp_path)
    executable = tmp_path / "bin" / "yoke"
    executable.parent.mkdir()
    executable.touch()
    stage = resolve_relay_instance(
        config_path=config_path,
        environment="stage",
        yoke_home=tmp_path / ".yoke",
    )
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        command = list(command)
        calls.append(command)
        returncode = 0
        if command[:2] == ["launchctl", "print"]:
            returncode = 0 if command[-1].endswith(stage.label) else 3
        return subprocess.CompletedProcess(command, returncode, "", "")

    installed = install_relay_launchd(
        home=tmp_path,
        yoke_home=tmp_path / ".yoke",
        config_path=config_path,
        environment="stage",
        executable=executable,
        runner=runner,
        platform="darwin",
        uid=501,
    )

    assert installed.loaded and installed.plist_current
    assert calls[0] == ["launchctl", "bootout", f"gui/501/{stage.label}"]
    assert calls[0][-1] != f"gui/501/{RELAY_LAUNCHD_LABEL}"
    prod_status = relay_launchd_status(
        home=tmp_path,
        yoke_home=tmp_path / ".yoke",
        config_path=config_path,
        environment="prod",
        executable=executable,
        runner=runner,
        platform="darwin",
        uid=501,
    )
    assert not prod_status.plist_present
    assert not prod_status.loaded
    assert prod_status.label == RELAY_LAUNCHD_LABEL


def test_invalid_connection_is_rejected_before_any_lifecycle_write(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    with pytest.raises(RelayInstanceError, match="missing"):
        install_relay_launchd(
            home=tmp_path,
            yoke_home=tmp_path / ".yoke",
            config_path=_config(tmp_path),
            environment="missing",
            executable=tmp_path / "bin" / "yoke",
            runner=lambda command, **_kwargs: calls.append(list(command)),
            platform="darwin",
        )

    assert calls == []
    assert not (tmp_path / "Library" / "LaunchAgents").exists()
