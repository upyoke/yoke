"""Full uninstall must outlive connection aliases without guessing ownership."""

from dataclasses import replace
import plistlib

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
from yoke_core.tools import install_session_relay as installer
from yoke_core.tools import session_relay_owned_uninstall as cleanup
from yoke_core.tools import session_relay_plist


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
    assert cleanup.uninstall_owned_relays(instance.yoke_home) == [instance.label]
    assert not path.exists()
    assert launchd.run_launchctl(
        ["launchctl", "print", f"gui/501/{instance.label}"]
    ).returncode


def test_preserves_service_owned_by_another_machine_home(saved):
    instance, _agents, write = saved
    foreign = replace(instance, yoke_home=instance.yoke_home.parent / "other")
    path = write(foreign)
    assert cleanup.uninstall_owned_relays(instance.yoke_home) == []
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
    assert cleanup.uninstall_owned_relays(instance.yoke_home) == [RELAY_BASE_LABEL]
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
        cleanup.uninstall_owned_relays(instance.yoke_home)
    assert path.exists()


def test_loaded_service_keeps_plist_for_retry(saved, monkeypatch):
    instance, _agents, write = saved
    path = write()
    monkeypatch.setattr(
        session_relay_plist, "wait_for_launchd_unload", lambda *a, **k: False
    )
    with pytest.raises(RelayInstallError, match="kept the exact machine relay loaded"):
        cleanup.uninstall_owned_relays(instance.yoke_home)
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
