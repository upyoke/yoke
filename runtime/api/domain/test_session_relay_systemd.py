"""Linux relay lifecycle, service escaping, and diagnosed refusal coverage."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import machine_config
from yoke_cli.config.session_relay_instance import RelayInstance
from yoke_core.tools import session_relay_systemd as service
from yoke_core.tools import session_relay_service as lifecycle
from yoke_core.tools.session_relay_plist import RelayInstallError
from yoke_core.tools.session_relay_release import RelayReleaseError


@pytest.fixture
def instance(tmp_path):
    return RelayInstance(
        environment="lab",
        config_path=tmp_path / "config.json",
        yoke_home=tmp_path / ".yoke",
        prod=False,
        label="com.upyoke.relay.test",
        state_dir=tmp_path / ".yoke/relay",
        follows_served_release=False,
    )


@pytest.fixture
def pid1(tmp_path):
    path = tmp_path / "pid1"
    path.write_text("systemd\n")
    return path


def runner(calls, *, linger="no", active=True, enabled=True, fail=None):
    def run(argv, **kwargs):
        calls.append(argv)
        if fail and fail in argv:
            return subprocess.CompletedProcess(argv, 1, "", "test refusal")
        if argv[0] == "loginctl":
            value = linger
        elif "is-active" in argv:
            value = "active" if active else "inactive"
        elif "is-enabled" in argv:
            value = "enabled" if enabled else "disabled"
        else:
            value = ""
        return subprocess.CompletedProcess(argv, 0, value, "")

    return run


def test_install_uses_existing_launcher_and_user_unit_without_linger(
    tmp_path, instance, pid1, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        service.relay_install,
        "converge_relay_launcher",
        lambda selected, **kw: calls.append(selected),
    )
    status = service.install_relay_systemd(
        instance=instance,
        home=tmp_path,
        runner=runner(calls),
        pid1_path=pid1,
    )
    assert status.loaded and status.enabled and status.unit_current
    assert lifecycle.relay_service_current(status)
    assert instance in calls
    assert ["systemctl", "--user", "enable", status.unit_path.name] in calls
    assert ["systemctl", "--user", "restart", status.unit_path.name] in calls
    assert not any("enable-linger" in call for call in calls if isinstance(call, list))
    assert status.unit_path.stat().st_mode & 0o777 == 0o600
    document = status.unit_path.read_text()
    assert "Restart=on-failure" in document
    assert "WantedBy=default.target" in document
    assert "--env" in document and '"lab"' in document
    assert str(instance.stdout_log) in document
    payload = lifecycle.relay_service_payload(status)
    assert payload["enabled"] and "logs out" in payload["logout_behavior"]
    assert "plist_path" not in payload


def test_unit_quotes_paths_and_prevents_expansion(instance, monkeypatch):
    launcher = Path('/home/user with spaces/100%/$HOME/"yoke"')
    monkeypatch.setattr(
        service.relay_install, "relay_launcher_path", lambda *a, **kw: launcher
    )
    document = service.relay_unit_document(instance, environ={"PATH": "/bin"})
    assert '100%%/$$HOME/\\"yoke\\"' in document
    assert f'Environment="{machine_config.CONFIG_FILE_ENV}=' in document
    assert "shell" not in document
    with pytest.raises(RelayInstallError, match="relay_unit_value_invalid"):
        service.relay_unit_document(
            replace(instance, environment="bad\nExecStart=other")
        )


@pytest.mark.parametrize("pid_name", ["bash", "init", "unreadable"])
def test_without_systemd_status_explains_unsupervised_and_install_refuses(
    tmp_path, instance, pid1, pid_name
):
    pid1.write_text(pid_name)
    calls = []
    status = service.relay_systemd_status(
        instance=instance, home=tmp_path, runner=runner(calls), pid1_path=pid1
    )
    assert not status.supported
    assert "not supervised" in status.reason and pid_name in status.reason
    with pytest.raises(RelayInstallError, match="relay_systemd_not_pid1"):
        service.install_relay_systemd(
            instance=instance, home=tmp_path, runner=runner(calls), pid1_path=pid1
        )
    assert calls == []
    assert not status.unit_path.exists()


@pytest.mark.parametrize(
    "linger, code",
    [("yes", "relay_linger_enabled"), ("unknown", "relay_linger_unknown")],
)
def test_linger_refuses_before_launcher_or_unit_mutation(
    tmp_path, instance, pid1, linger, code
):
    calls = []
    with pytest.raises(RelayInstallError, match=code):
        service.install_relay_systemd(
            instance=instance,
            home=tmp_path,
            runner=runner(calls, linger=linger),
            pid1_path=pid1,
        )
    assert not service.relay_unit_path(instance, home=tmp_path).exists()
    assert not any("enable" in call for call in calls)


def test_missing_user_manager_teaches_login_session(tmp_path, instance, pid1):
    status = service.relay_systemd_status(
        instance=instance,
        home=tmp_path,
        runner=runner([], fail="show-environment"),
        pid1_path=pid1,
    )
    assert not status.supported
    assert "user_manager_unavailable" in status.reason and "PAM" in status.reason


def test_release_failure_keeps_existing_unit_untouched(
    tmp_path, instance, pid1, monkeypatch
):
    path = service.relay_unit_path(instance, home=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("working unit")

    def refuse(*args, **kwargs):
        raise RelayReleaseError("relay_release_fetch_failed", "fetch refused")

    monkeypatch.setattr(service.relay_install, "converge_relay_launcher", refuse)
    calls = []
    with pytest.raises(RelayInstallError, match="fetch refused"):
        service.install_relay_systemd(
            instance=instance, home=tmp_path, runner=runner(calls), pid1_path=pid1
        )
    assert path.read_text() == "working unit"
    assert not any("restart" in call for call in calls)


def test_start_failure_is_not_install_success(tmp_path, instance, pid1, monkeypatch):
    monkeypatch.setattr(
        service.relay_install, "converge_relay_launcher", lambda *a, **kw: None
    )
    with pytest.raises(
        RelayInstallError, match="relay_systemd_command_failed.*test refusal"
    ):
        service.install_relay_systemd(
            instance=instance,
            home=tmp_path,
            runner=runner([], fail="enable"),
            pid1_path=pid1,
        )
    with pytest.raises(RelayInstallError, match="relay_systemd_not_active"):
        service.install_relay_systemd(
            instance=instance,
            home=tmp_path,
            runner=runner([], active=False),
            pid1_path=pid1,
        )


@pytest.mark.parametrize("operation", ["install", "uninstall"])
def test_service_operation_waits_for_graceful_stop_beyond_probe_deadline(
    tmp_path, instance, pid1, monkeypatch, operation
):
    monkeypatch.setattr(
        service.relay_install, "converge_relay_launcher", lambda *a, **kw: None
    )
    path = service.relay_unit_path(instance, home=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("existing unit")
    fallback = runner([], active=operation == "install", enabled=operation == "install")
    waited = []
    graceful_stop_seconds = 31

    def graceful_stop(argv, **kwargs):
        if "restart" in argv or "--now" in argv:
            if kwargs["timeout"] < graceful_stop_seconds:
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            waited.append(graceful_stop_seconds)
        return fallback(argv, **kwargs)

    action = getattr(service, f"{operation}_relay_systemd")
    status = action(
        instance=instance, home=tmp_path, runner=graceful_stop, pid1_path=pid1
    )
    assert waited == [graceful_stop_seconds]
    assert status.loaded == (operation == "install")


def test_service_timeout_teaches_unsettled_job_without_claiming_manager_missing(
    tmp_path, instance, pid1, monkeypatch
):
    monkeypatch.setattr(
        service.relay_install, "converge_relay_launcher", lambda *a, **kw: None
    )
    fallback = runner([])

    def timeout(argv, **kwargs):
        if "restart" in argv:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return fallback(argv, **kwargs)

    with pytest.raises(RelayInstallError) as raised:
        service.install_relay_systemd(
            instance=instance, home=tmp_path, runner=timeout, pid1_path=pid1
        )
    assert raised.value.code == "relay_systemd_command_timeout"
    assert "job may still be running" in str(raised.value)
    assert "list-jobs" in str(raised.value) and "before retrying" in str(raised.value)
    assert "Log in" not in str(raised.value)


def test_uninstall_disables_owned_unit_and_retains_relay_state(
    tmp_path, instance, pid1
):
    path = service.relay_unit_path(instance, home=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("unit")
    instance.state_dir.mkdir(parents=True)
    (instance.state_dir / "receipt").write_text("durable")
    calls = []
    status = service.uninstall_relay_systemd(
        instance=instance,
        home=tmp_path,
        runner=runner(calls, active=False, enabled=False),
        pid1_path=pid1,
    )
    assert not status.unit_present and not status.loaded
    assert ["systemctl", "--user", "disable", "--now", path.name] in calls
    assert (instance.state_dir / "receipt").read_text() == "durable"


def test_linux_lifecycle_routes_all_operations_to_systemd(monkeypatch):
    monkeypatch.setattr(lifecycle.sys, "platform", "linux")
    for action, name in [
        ("install", "install_relay_systemd"),
        ("status", "relay_systemd_status"),
        ("uninstall", "uninstall_relay_systemd"),
    ]:
        monkeypatch.setattr(service, name, lambda **kw: kw["instance"])
        assert (
            lifecycle.relay_service_operation(action, instance="selected") == "selected"
        )


def test_uninstall_cannot_report_success_while_owned_unit_remains_active(
    tmp_path, instance, pid1
):
    with pytest.raises(RelayInstallError, match="relay_systemd_not_stopped"):
        service.uninstall_relay_systemd(
            instance=instance, home=tmp_path, runner=runner([]), pid1_path=pid1
        )
