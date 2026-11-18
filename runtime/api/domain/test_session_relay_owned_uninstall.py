"""Full uninstall must outlive connection aliases without guessing ownership."""

from dataclasses import replace
import plistlib
import subprocess

import pytest

from yoke_contracts.machine_config.relay_instance import (
    RELAY_BASE_LABEL,
    RELAY_STATE_ROOT_NAME,
    RelayInstance,
    relay_instance_label,
)
from yoke_core.domain import launchctl_boundary as launchd
from yoke_core.domain.relay_launchd_status import (
    RelayInstallError,
    relay_launchd_paths,
    relay_plist_document,
)
from yoke_core.domain.relay_systemd_status import relay_unit_document, relay_unit_path
from yoke_core.tools import install_session_relay as installer
from yoke_core.tools import session_relay_owned_uninstall as cleanup
from yoke_core.tools import session_relay_plist
from yoke_core.tools import session_relay_systemd


@pytest.fixture
def saved(tmp_path, monkeypatch):
    machine_home = tmp_path / "machine"
    config = machine_home / "config.json"
    label = relay_instance_label(config_path=config, environment="retired")
    instance = RelayInstance(
        "retired",
        config,
        machine_home,
        False,
        label,
        machine_home / RELAY_STATE_ROOT_NAME / label.rsplit(".", 1)[-1],
    )
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    monkeypatch.setattr(cleanup, "launch_agents_dir", lambda **kwargs: agents)
    monkeypatch.setattr(
        session_relay_plist,
        "relay_launchd_paths",
        lambda **kwargs: replace(
            relay_launchd_paths(instance=kwargs["instance"]),
            plist=agents / f"{kwargs['instance'].label}.plist",
        ),
    )
    # Keep the canonical lifecycle's runner/wait, in its disposable launchd domain.
    uninstall = session_relay_plist.uninstall_relay_launchd
    monkeypatch.setattr(
        cleanup,
        "uninstall_relay_launchd",
        lambda **kwargs: uninstall(
            **kwargs,
            platform="darwin",
            uid=501,
        ),
    )

    def write(value=instance):
        paths = replace(
            relay_launchd_paths(instance=value), plist=agents / f"{value.label}.plist"
        )
        path = paths.plist
        path.write_bytes(plistlib.dumps(relay_plist_document(paths=paths)))
        launchd.run_launchctl(["launchctl", "bootstrap", "gui/501", str(path)])
        return path

    return instance, agents, write


@pytest.mark.parametrize("config_exists", [False, True])
def test_unloads_saved_service_after_alias_or_config_removed(saved, config_exists):
    instance, _agents, write = saved
    if config_exists:
        instance.config_path.parent.mkdir(parents=True)
        instance.config_path.write_text('{"connections":{}}')
    path = write()
    assert cleanup.uninstall_owned_relays(instance.yoke_home, platform="darwin") == [instance.label]
    assert not path.exists()
    assert launchd.run_launchctl(
        ["launchctl", "print", f"gui/501/{instance.label}"]
    ).returncode


def test_preserves_service_owned_by_another_machine_home(saved):
    instance, _agents, write = saved
    foreign = replace(instance, yoke_home=instance.yoke_home.parent / "other")
    path = write(foreign)
    assert cleanup.uninstall_owned_relays(instance.yoke_home, platform="darwin") == []
    assert path.is_file()
    assert (
        launchd.run_launchctl(
            ["launchctl", "print", f"gui/501/{instance.label}"]
        ).returncode
        == 0
    )


def test_removes_owned_shared_legacy_service(saved):
    instance, _agents, write = saved
    shared = replace(
        instance, label=RELAY_BASE_LABEL, state_dir=instance.yoke_home / "relay"
    )
    path = write(shared)
    assert cleanup.uninstall_owned_relays(instance.yoke_home, platform="darwin") == [RELAY_BASE_LABEL]
    assert not path.exists()


@pytest.mark.parametrize(
    "damage", ["label", "command", "launcher", "unreadable", "symlink"]
)
def test_unproven_service_is_retained_and_fails_cleanup(saved, damage):
    instance, _agents, write = saved
    path = write()
    doc = plistlib.loads(path.read_bytes())
    if damage == "label":
        doc["Label"] = RELAY_BASE_LABEL + ".wrong"
    elif damage == "command":
        doc["ProgramArguments"][3:] = ["foreign", "serve"]
    elif damage == "launcher":
        doc["ProgramArguments"][0] = "/foreign/program"
    if damage == "symlink":
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    else:
        path.write_bytes(
            b"not a plist" if damage == "unreadable" else plistlib.dumps(doc)
        )
    with pytest.raises(RelayInstallError, match="uninstall_relay_ownership_unproven"):
        cleanup.uninstall_owned_relays(instance.yoke_home, platform="darwin")
    assert path.exists()


def test_loaded_service_keeps_plist_for_retry(saved, monkeypatch):
    instance, _agents, write = saved
    path = write()
    monkeypatch.setattr(
        session_relay_plist, "wait_for_launchd_unload", lambda *a, **k: False
    )
    with pytest.raises(RelayInstallError, match="kept the exact machine relay loaded"):
        cleanup.uninstall_owned_relays(instance.yoke_home, platform="darwin")
    assert path.is_file()


def test_installer_cleanup_does_not_resolve_retired_connection(saved, monkeypatch):
    instance, _agents, write = saved
    path = write()
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    monkeypatch.setattr(
        installer,
        "resolve_relay_instance",
        lambda **kwargs: pytest.fail("alias resolved"),
    )
    assert (
        installer.main(["uninstall-owned", "--machine-home", str(instance.yoke_home)])
        == 0
    )
    assert not path.exists()


@pytest.mark.posix_only(reason="systemd user unit lifecycle requires POSIX")
@pytest.mark.parametrize("stop_fails", [False, True])
def test_linux_installer_removes_retired_unit_or_reports_stop_failure(
    tmp_path, monkeypatch, stop_fails
):
    machine_home = tmp_path / "machine % directory"
    machine_home.mkdir()
    config = machine_home / "config.json"
    config.write_text('{"connections":{}}')
    label = relay_instance_label(config_path=config, environment="retired")
    instance = RelayInstance(
        "retired",
        config,
        machine_home,
        False,
        label,
        machine_home / RELAY_STATE_ROOT_NAME / label.rsplit(".", 1)[-1],
        follows_served_release=True,
    )
    path = relay_unit_path(instance, home=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(relay_unit_document(instance))
    foreign_config = tmp_path / "other" / "config.json"
    foreign_label = relay_instance_label(config_path=foreign_config, environment="retired")
    foreign = replace(instance, config_path=foreign_config, yoke_home=foreign_config.parent,
                      label=foreign_label)
    foreign_path = relay_unit_path(foreign, home=tmp_path)
    foreign_path.write_text(relay_unit_document(foreign))
    pid1 = tmp_path / "pid1"
    pid1.write_text("systemd\n")
    active = True
    calls = []

    def run(argv, **kwargs):
        nonlocal active
        calls.append(argv)
        if "disable" in argv:
            if stop_fails:
                return subprocess.CompletedProcess(argv, 1, "", "stop refused")
            active = False
        output = "no" if argv[0] == "loginctl" else ""
        if "is-active" in argv:
            output = "active" if active else "inactive"
        if "is-enabled" in argv:
            output = "enabled" if active else "disabled"
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(cleanup, "relay_unit_directory", lambda: path.parent)
    monkeypatch.setattr(
        cleanup,
        "uninstall_relay_systemd",
        lambda **kwargs: session_relay_systemd.uninstall_relay_systemd(
            **kwargs, home=tmp_path, runner=run, pid1_path=pid1
        ),
    )
    assert installer.main(["uninstall-owned", "--machine-home", str(machine_home)]) == int(stop_fails)
    assert ["systemctl", "--user", "disable", "--now", path.name] in calls
    assert active is stop_fails
    assert path.exists() is stop_fails
    assert foreign_path.exists()
    assert all(foreign_path.name not in call for call in calls)
