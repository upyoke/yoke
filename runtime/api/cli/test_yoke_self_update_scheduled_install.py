"""``install_release`` retries through the desktop task only on the guard refusal."""

import subprocess

import pytest

from yoke_contracts.windows_one_shot_task import OneShotRefused, OneShotResult
from yoke_cli.config import scheduled_install, self_update
from yoke_cli.self_host import release_target

TARGET = release_target.ReleaseTarget(
    version="0.2.0.2", source_commit="", image="", base_url="https://x",
    channel="stable", installer_url="https://x/dist/install.py",
)
GUARD = "windows_untrusted_mount_point: run from a local PowerShell"


@pytest.fixture
def host(monkeypatch):
    state = {"direct": subprocess.CompletedProcess([], 1, "", GUARD), "calls": [],
             "result": OneShotResult(0, "ok"), "version": TARGET.version}
    monkeypatch.setattr(release_target, "fetch_installer", lambda _t: b"installer")
    monkeypatch.setattr(release_target, "run_installer", lambda *_a, **_k: state["direct"])

    def scheduled(target, data, env=None):
        state["calls"].append((target, data, env))
        if isinstance(state["result"], Exception):
            raise state["result"]
        return state["result"]

    monkeypatch.setattr(scheduled_install, "run_installer", scheduled)
    monkeypatch.setattr(self_update, "_probe_version", lambda *_a: state["version"])
    return state


def test_guard_refusal_installs_through_the_task_and_probes(host):
    assert self_update.install_release(TARGET, "yoke") == TARGET.version
    assert host["calls"] == [(TARGET, b"installer", None)]


def test_other_failure_propagates_without_the_scheduler(host):
    host["direct"] = subprocess.CompletedProcess([], 1, "", "disk full")
    with pytest.raises(self_update.SelfUpdateError, match="disk full") as caught:
        self_update.install_release(TARGET, "yoke")
    assert not isinstance(caught.value, self_update.ScheduledInstallRefused)
    assert host["calls"] == []


def test_success_needs_no_scheduler(host):
    host["direct"] = subprocess.CompletedProcess([], 0, "", "")
    assert self_update.install_release(TARGET, "yoke") == TARGET.version
    assert host["calls"] == []


@pytest.mark.parametrize(
    "result, expected",
    [
        (OneShotResult(5, "uv broke"), "exited 5"),
        (OneShotRefused("yokeqa is not signed in", "uv broke"), "not signed in"),
    ],
)
def test_failed_task_is_the_named_refusal_with_desktop_recovery(host, result, expected):
    host["result"] = result
    with pytest.raises(self_update.ScheduledInstallRefused) as caught:
        self_update.install_release(TARGET, "yoke")
    text = str(caught.value)
    assert text.startswith("windows_scheduled_install_failed")
    assert expected in text and "uv broke" in text
    assert f"`yoke update --version {TARGET.version}` in PowerShell" in text
    assert "sign in at this machine's desktop" in text


def test_wrong_version_after_the_task_is_the_named_refusal(host):
    host["version"] = "0.2.0.1"
    with pytest.raises(self_update.ScheduledInstallRefused, match="0.2.0.1"):
        self_update.install_release(TARGET, "yoke")


def test_task_environment_carries_install_paths_and_no_credentials():
    selected = scheduled_install.installer_environment(
        {"PATH": "p", "UV_TOOL_BIN_DIR": "b", "YOKE_API_TOKEN": "secret", "GH_TOKEN": "s"}
    )
    assert selected == {"PATH": "p", "UV_TOOL_BIN_DIR": "b"}


def test_wait_bound_is_the_installer_timeout():
    assert scheduled_install.SCHEDULED_INSTALL_LIMIT_SECONDS == int(
        release_target.INSTALLER_RUN_TIMEOUT_SECONDS
    )
