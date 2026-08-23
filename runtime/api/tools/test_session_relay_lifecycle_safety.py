"""Safety boundaries for environment-qualified relay lifecycle operations."""

from __future__ import annotations

import json
from pathlib import Path
import plistlib
import subprocess
from types import SimpleNamespace

import pytest

from yoke_cli.config.session_relay_instance import (
    PROD_RELAY_LABEL,
    RelayInstanceError,
    resolve_relay_instance,
)
from yoke_core.tools import install_session_relay
from yoke_core.tools.session_relay_plist import (
    RelayInstallError,
    install_relay_launchd,
    relay_launchd_paths,
    uninstall_relay_launchd,
)


def _write_config(tmp_path: Path) -> Path:
    path = tmp_path / ".yoke" / "config.json"
    path.parent.mkdir(parents=True)
    token = lambda name: {  # noqa: E731 - compact fixture constructor
        "kind": "token_file",
        "path": f"~/.yoke/secrets/{name}.token",
    }
    connections = {
        name: {
            "transport": "https",
            "prod": prod,
            "api_url": f"https://{name}.example.test",
            "credential_source": token(name),
        }
        for name, prod in (("prod", True), ("stage", False))
    }
    connections["prod-db-admin"] = {
        "transport": "local-postgres",
        "prod": True,
        "credential_source": {
            "kind": "dsn_file",
            "path": "~/.yoke/secrets/prod-db-admin.dsn",
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


def test_prod_db_admin_cannot_resolve_a_relay_instance(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    with pytest.raises(RelayInstanceError, match="requires an https"):
        install_relay_launchd(
            home=tmp_path,
            config_path=_write_config(tmp_path),
            environment="prod-db-admin",
            yoke_home=tmp_path / ".yoke",
            executable=tmp_path / "bin" / "yoke",
            runner=lambda command, **_kwargs: calls.append(list(command)),
            platform="darwin",
        )
    assert calls == []


def test_multiple_prod_https_connections_refuse_the_legacy_identity(
    tmp_path: Path,
) -> None:
    config_path = _write_config(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["connections"]["prod-alias"] = {
        **payload["connections"]["prod"],
        "api_url": "https://prod-alias.example.test",
    }
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RelayInstanceError, match="exactly one prod https"):
        resolve_relay_instance(
            config_path=config_path,
            environment="prod",
            yoke_home=tmp_path / ".yoke",
        )


def test_stage_upgrade_retires_the_unpinned_legacy_job(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    executable = tmp_path / "bin" / "yoke"
    executable.parent.mkdir()
    executable.touch()
    legacy_path = tmp_path / "Library" / "LaunchAgents" / f"{PROD_RELAY_LABEL}.plist"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(
        plistlib.dumps(
            {
                "Label": PROD_RELAY_LABEL,
                "ProgramArguments": [str(executable), "relay", "serve-once"],
            }
        )
    )
    calls: list[list[str]] = []
    stage = resolve_relay_instance(
        config_path=config_path,
        environment="stage",
        yoke_home=tmp_path / ".yoke",
    )

    def runner(command, **_kwargs):
        command = list(command)
        calls.append(command)
        returncode = 0
        if command[1] == "print":
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
    assert not legacy_path.exists()
    assert calls[:2] == [
        ["launchctl", "bootout", f"gui/501/{PROD_RELAY_LABEL}"],
        ["launchctl", "print", f"gui/501/{PROD_RELAY_LABEL}"],
    ]


def test_uninstall_refuses_success_when_exact_job_stays_loaded(
    tmp_path: Path,
) -> None:
    config_path = _write_config(tmp_path)
    instance = resolve_relay_instance(
        config_path=config_path,
        environment="prod",
        yoke_home=tmp_path / ".yoke",
    )
    plist_path = relay_launchd_paths(home=tmp_path, instance=instance).plist
    plist_path.parent.mkdir(parents=True)
    plist_path.write_bytes(b"still needed for recovery")

    with pytest.raises(RelayInstallError, match="kept the exact"):
        uninstall_relay_launchd(
            home=tmp_path,
            instance=instance,
            runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command, 0, "", ""
            ),
            platform="darwin",
            uid=501,
        )

    assert plist_path.is_file()


@pytest.mark.parametrize(
    ("present", "loaded", "current", "expected"),
    (
        (False, False, False, 1),
        (True, False, True, 1),
        (True, True, False, 1),
        (True, True, True, 0),
    ),
)
def test_legacy_status_helper_uses_the_same_health_contract(
    monkeypatch, present: bool, loaded: bool, current: bool, expected: int
) -> None:
    status = SimpleNamespace(
        supported=True,
        plist_present=present,
        loaded=loaded,
        plist_current=current,
    )
    monkeypatch.setattr(install_session_relay, "relay_launchd_status", lambda: status)

    assert install_session_relay.main(["status"]) == expected
