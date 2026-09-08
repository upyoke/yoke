"""Relay lifecycle for a universe this machine serves itself.

A local install has no served release to follow and no API token to reuse, so
these cover what that changes: which connections may own a relay, what launchd
is pointed at, how a missing launcher is refused, and how status reports a
relay whose build is simply the machine's own install.
"""

from __future__ import annotations

import json
from pathlib import Path
import plistlib
import subprocess
from types import SimpleNamespace

import pytest

from yoke_cli.config.session_relay_instance import (
    NON_PROD_RELAY_LABEL_PREFIX,
    resolve_relay_instance,
)
from yoke_core.tools import install_session_relay
from yoke_core.tools import session_relay_local_install as local_install
from yoke_core.tools.session_relay_plist import (
    RELAY_LAUNCHD_LABEL,
    RelayInstallError,
    install_relay_launchd,
    relay_launchd_paths,
    relay_plist_document,
)


def _config(tmp_path: Path) -> Path:
    """A machine holding a hosted connection and a local universe at once."""
    path = tmp_path / ".yoke" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    connections = {
        "prod": {
            "transport": "https",
            "prod": True,
            "api_url": "https://prod.example.test",
            "credential_source": {
                "kind": "token_file",
                "path": "~/.yoke/secrets/prod.token",
            },
        },
        "local": {
            "transport": "local-postgres",
            "prod": False,
            "credential_source": {
                "kind": "dsn_file",
                "path": "~/.yoke/secrets/local.dsn",
            },
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


def _installed_launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    launcher = tmp_path / "bin" / "yoke"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.touch(mode=0o755)
    monkeypatch.setattr(
        local_install, "local_launcher_candidates", lambda: (launcher,)
    )
    return launcher


def test_local_universe_owns_a_relay_that_runs_the_installed_yoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A local install gets a relay, and it runs this machine's own Yoke.

    Nothing is fetched: the machine serving the universe is the machine
    running the relay, so the installed launcher is already the served build.
    """
    launcher = _installed_launcher(tmp_path, monkeypatch)
    config_path = _config(tmp_path)

    instance = resolve_relay_instance(
        config_path=config_path,
        environment="local",
        yoke_home=tmp_path / ".yoke",
    )

    assert not instance.follows_served_release
    assert not instance.prod
    assert instance.label.startswith(NON_PROD_RELAY_LABEL_PREFIX)

    document = relay_plist_document(
        paths=relay_launchd_paths(home=tmp_path, instance=instance),
        environ={"PATH": "/usr/bin"},
    )

    assert document["ProgramArguments"] == [
        str(launcher),
        "--env",
        "local",
        "relay",
        "serve",
    ]


def test_local_relay_install_refuses_by_name_without_an_installed_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing component is named with its repair, never silently skipped."""
    missing = tmp_path / "bin" / "yoke"
    monkeypatch.setattr(
        local_install, "local_launcher_candidates", lambda: (missing,)
    )
    calls: list[list[str]] = []

    with pytest.raises(RelayInstallError) as raised:
        install_relay_launchd(
            home=tmp_path,
            config_path=_config(tmp_path),
            environment="local",
            yoke_home=tmp_path / ".yoke",
            runner=lambda command, **_kwargs: calls.append(list(command)),
            platform="darwin",
        )

    assert raised.value.code == local_install.LOCAL_LAUNCHER_MISSING
    assert str(missing) in str(raised.value)
    assert local_install.LOCAL_LAUNCHER_RECOVERY in str(raised.value)
    # The refusal lands before launchd is touched, so a loaded relay survives.
    assert calls == []


def test_local_install_never_boots_out_a_healthy_prod_relay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A local universe can share a machine with a hosted relay.

    Both are installable now, so the local install must leave the pinned prod
    job and its plist exactly where they are.
    """
    _installed_launcher(tmp_path, monkeypatch)
    config_path = _config(tmp_path)
    local = resolve_relay_instance(
        config_path=config_path,
        environment="local",
        yoke_home=tmp_path / ".yoke",
    )
    prod = resolve_relay_instance(
        config_path=config_path,
        environment="prod",
        yoke_home=tmp_path / ".yoke",
    )
    prod_paths = relay_launchd_paths(home=tmp_path, instance=prod)
    prod_paths.plist.parent.mkdir(parents=True)
    prod_paths.plist.write_bytes(plistlib.dumps(relay_plist_document(paths=prod_paths)))
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        command = list(command)
        calls.append(command)
        returncode = 0
        if command[:2] == ["launchctl", "print"]:
            local_loaded = any(call[1] == "bootstrap" for call in calls)
            returncode = 0 if local_loaded and command[-1].endswith(local.label) else 3
        return subprocess.CompletedProcess(command, returncode, "", "")

    installed = install_relay_launchd(
        home=tmp_path,
        yoke_home=tmp_path / ".yoke",
        config_path=config_path,
        environment="local",
        runner=runner,
        platform="darwin",
        uid=501,
    )

    assert installed.loaded and installed.plist_current
    assert not installed.follows_served_release
    assert prod_paths.plist.is_file()
    assert not any(
        call[-1] == f"gui/501/{RELAY_LAUNCHD_LABEL}"
        for call in calls
        if call[:2] == ["launchctl", "bootout"]
    )


@pytest.mark.parametrize("ready", (True, False))
def test_local_relay_status_reports_the_installed_launcher(
    monkeypatch, capsys, ready: bool
) -> None:
    """A local relay's health is its launcher, not a release pin it never has."""
    monkeypatch.setattr(
        install_session_relay,
        "resolve_relay_instance",
        lambda **_kwargs: SimpleNamespace(follows_served_release=False),
    )
    monkeypatch.setattr(
        install_session_relay,
        "relay_launchd_status",
        lambda **_kwargs: SimpleNamespace(
            supported=True,
            plist_present=True,
            loaded=True,
            plist_current=True,
            environment="local",
            follows_served_release=False,
        ),
    )
    launcher = Path("/opt/homebrew/bin/yoke")
    monkeypatch.setattr(install_session_relay, "local_launcher_path", lambda: launcher)
    monkeypatch.setattr(
        install_session_relay, "local_launcher_ready", lambda _path: ready
    )

    def unreachable(**_kwargs):
        raise AssertionError("a local relay must not read a served release")

    monkeypatch.setattr(install_session_relay, "relay_release_status", unreachable)

    assert install_session_relay.main(["status"]) == (0 if ready else 1)
    printed = capsys.readouterr().out
    assert str(launcher) in printed
    assert f"runnable={'yes' if ready else 'no'}" in printed
