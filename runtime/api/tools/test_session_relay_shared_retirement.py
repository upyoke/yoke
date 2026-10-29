"""Shared relay retirement uses exact ownership and preserves worker custody."""

from dataclasses import replace
import plistlib
from unittest.mock import Mock

import pytest

from yoke_cli.config.session_relay_instance import RelayInstance, RELAY_BASE_LABEL
from yoke_core.tools import session_relay_shared_retirement as retirement
from yoke_core.tools import session_relay_plist as launchd
from yoke_core.tools import session_relay_systemd as systemd


@pytest.fixture
def instance(tmp_path):
    return RelayInstance(
        environment="stage",
        config_path=tmp_path / "config.json",
        yoke_home=tmp_path / ".yoke",
        protected=True,
        label=RELAY_BASE_LABEL + ".digest",
        state_dir=tmp_path / ".yoke/relay-instances/digest",
    )


def _document(instance, tmp_path, platform):
    shared = retirement._shared(instance)
    if platform == "launchd":
        paths = launchd.relay_launchd_paths(home=tmp_path, instance=shared)
        path = paths.plist
        payload = plistlib.dumps(launchd.relay_plist_document(paths=paths, environ={}))
    else:
        path = systemd.relay_unit_path(shared, home=tmp_path)
        payload = systemd.relay_unit_document(shared, environ={}).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _retire(instance, tmp_path, platform):
    if platform == "launchd":
        retirement.retire_shared_launchd(
            instance, home=tmp_path, runner=Mock(), uid=501
        )
    else:
        retirement.retire_shared_systemd(
            instance, home=tmp_path, runner=Mock(), pid1_path=tmp_path / "pid1"
        )


@pytest.mark.parametrize("platform", ["launchd", "systemd"])
def test_exact_owner_retires_service_without_moving_old_state(
    instance, tmp_path, monkeypatch, platform
):
    path = _document(instance, tmp_path, platform)
    state = retirement._shared(instance).state_dir
    state.mkdir(parents=True)
    evidence = state / "evidence"
    evidence.write_text("keep")
    stopped = Mock()
    module = launchd if platform == "launchd" else systemd
    name = (
        "uninstall_relay_launchd"
        if platform == "launchd"
        else "uninstall_relay_systemd"
    )
    monkeypatch.setattr(module, name, stopped)
    _retire(instance, tmp_path, platform)
    assert stopped.call_args.kwargs["instance"].label == RELAY_BASE_LABEL
    assert evidence.read_text() == "keep"
    assert path.exists()  # Only the native uninstaller owns removal.


@pytest.mark.parametrize("platform", ["launchd", "systemd"])
def test_foreign_connection_service_stays_untouched(
    instance, tmp_path, monkeypatch, platform
):
    _document(replace(instance, environment="other"), tmp_path, platform)
    stopped = Mock()
    monkeypatch.setattr(
        launchd if platform == "launchd" else systemd,
        "uninstall_relay_launchd"
        if platform == "launchd"
        else "uninstall_relay_systemd",
        stopped,
    )
    _retire(instance, tmp_path, platform)
    stopped.assert_not_called()


@pytest.mark.parametrize("platform", ["launchd", "systemd"])
def test_live_or_unknown_worker_blocks_retirement(
    instance, tmp_path, monkeypatch, platform
):
    path = _document(instance, tmp_path, platform)
    directory = (
        retirement._shared(instance).state_dir / retirement.SUPERVISION_DIRECTORY_NAME
    )
    directory.mkdir(parents=True)
    (directory / "worker.json").write_text("{}")
    monkeypatch.setattr(retirement, "custody_state", lambda record: "unknown")
    with pytest.raises(launchd.RelayInstallError, match="close its worker sessions"):
        _retire(instance, tmp_path, platform)
    assert path.exists()


@pytest.mark.parametrize("platform", ["launchd", "systemd"])
def test_unreadable_document_is_preserved(instance, tmp_path, platform):
    path = _document(instance, tmp_path, platform)
    path.write_text("invalid")
    with pytest.raises(launchd.RelayInstallError, match="retirement_blocked"):
        _retire(instance, tmp_path, platform)
    assert path.read_text() == "invalid"
