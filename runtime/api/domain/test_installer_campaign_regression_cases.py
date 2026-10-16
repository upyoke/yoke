"""Recovery recipes use executable method contracts and fail closed."""

from io import BytesIO
from pathlib import Path
from subprocess import CompletedProcess
import shutil
import shlex
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib import request

import pytest

from yoke_contracts.codex_config_posture import plan
from yoke_core.domain.installer_campaign_regression_cases import (
    INSTALLER_RECOVERY_CASES,
    _LATE_HARNESS_SCRIPT,
    _STALE_RELEASE_SCRIPT,
    _UNINSTALL_WAIT_SCRIPT,
)
from yoke_core.domain.machine_qa_method_contracts import validate_machine_method_config
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)
from yoke_core.domain.ssh_mac_host_control import SshMacHostControl
from yoke_core.domain.ssh_linux_host_control import SshLinuxHostControl
from runtime.api.domain.test_qa_release_channel_target import _target


def test_every_recovery_recipe_satisfies_its_method_contract():
    for case in INSTALLER_RECOVERY_CASES:
        validate_machine_method_config(
            case["method_id"],
            case["method_config"],
            entry_surface=case["entry_surface"],
            required_completion=case["required_completion"],
        )


def test_projected_recovery_entries_expand_through_both_real_host_adapters():
    control = SimpleNamespace(
        path_state=SimpleNamespace(yoke_bin="/tmp/fixture/bin/yoke")
    )
    cases = installer_campaign_cases_for_target(
        _target("prod"),
        primary_machine="primary-test",
        joining_machine="joining-test",
    )
    for case in cases:
        if case["entry_surface"]:
            mac = SshMacHostControl._resolve_entry_surface(
                control, case["entry_surface"]
            )
            linux = SshLinuxHostControl._entry_surface(control, case["entry_surface"])
            assert mac == linux
            assert "{yoke_bin}" not in mac


def test_stale_lookup_selects_the_highest_published_predecessor(monkeypatch, capsys):
    def open_response(url, **kwargs):
        if url.endswith(".json"):
            return BytesIO(
                b'{"version":"2.0.0","index_url":"https://example.invalid/simple"}'
            )
        return BytesIO(
            b'<a href="yoke_cli-1.0-py3-none-any.whl">older</a>'
            b'<a href="yoke_cli-1.5-py3-none-any.whl">previous</a>'
            b'<a href="yoke_cli-2.1-py3-none-any.whl">newer</a>'
        )

    monkeypatch.setattr(request, "urlopen", open_response)
    monkeypatch.setattr(sys, "argv", ["fixture", "https://example.invalid", "stable"])
    exec(compile(_STALE_RELEASE_SCRIPT, "stale_fixture", "exec"), {})
    assert capsys.readouterr().out.strip() == "2.0.0 1.5"


def test_stale_lookup_network_failure_teaches_recovery(monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("unavailable")

    monkeypatch.setattr(request, "urlopen", refuse)
    monkeypatch.setattr(sys, "argv", ["fixture", "https://example.invalid", "stable"])
    with pytest.raises(SystemExit, match="stale_release_lookup_failed"):
        exec(compile(_STALE_RELEASE_SCRIPT, "stale_fixture", "exec"), {})


@pytest.mark.parametrize("removed_after", [2, None])
def test_uninstall_waits_for_deferred_removal_or_names_timeout(
    monkeypatch, removed_after
):
    clock = [0]
    with monkeypatch.context() as patch:
        patch.setattr(sys, "argv", ["fixture", "/tmp/fixture-launcher"])
        patch.setattr(time, "monotonic", lambda: clock[0])
        patch.setattr(time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + 1))
        patch.setattr(
            Path,
            "exists",
            lambda path: removed_after is None or clock[0] < removed_after,
        )
        if removed_after is None:
            with pytest.raises(SystemExit, match="uninstall_handoff_incomplete"):
                exec(compile(_UNINSTALL_WAIT_SCRIPT, "uninstall_fixture", "exec"), {})
        else:
            exec(compile(_UNINSTALL_WAIT_SCRIPT, "uninstall_fixture", "exec"), {})
            assert clock[0] == removed_after


def _late_fixture(monkeypatch, tmp_path, setup_returncode):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    executable = tmp_path / "codex"
    executable.write_text("fixture binary")
    monkeypatch.setattr(shutil, "which", lambda name: str(executable))
    monkeypatch.setattr(
        sys, "argv", ["fixture", "setup-fixture", str(tmp_path / "late-codex")]
    )

    def run(argv, **kwargs):
        if kwargs.get("shell") and executable.exists() and setup_returncode == 0:
            config = Path(kwargs["env"]["CODEX_HOME"]) / "config.toml"
            config.write_text(plan("")[0])
        return CompletedProcess(argv, setup_returncode if kwargs.get("shell") else 0)

    monkeypatch.setattr(subprocess, "run", run)
    return executable


def test_failed_setup_restores_the_preserved_harness(monkeypatch, tmp_path):
    executable = _late_fixture(monkeypatch, tmp_path, 1)
    home = tmp_path / ".codex"
    home.mkdir()
    marker = home / "preserved-file"
    marker.write_text("preserve without reading during the fixture")
    with pytest.raises(SystemExit, match="late_harness_setup_failed"):
        exec(compile(_LATE_HARNESS_SCRIPT, "late_fixture", "exec"), {})
    assert executable.read_text() == "fixture binary"
    assert not executable.with_name("codex.installer-qa-saved").exists()
    assert marker.is_file()
    assert not home.with_name(".codex.installer-qa-saved").exists()


def test_late_discovery_uses_absent_then_available_disposable_home(
    monkeypatch, tmp_path
):
    executable = _late_fixture(monkeypatch, tmp_path, 0)
    home = tmp_path / ".codex"
    home.mkdir()
    observed = []

    def run(argv, **kwargs):
        if kwargs.get("shell"):
            fixture_home = Path(kwargs["env"]["CODEX_HOME"])
            assert fixture_home != home
            assert home.is_dir()
            observed.append((executable.exists(), fixture_home.exists()))
        return CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SystemExit, match="late_harness_permissions_missing"):
        exec(compile(_LATE_HARNESS_SCRIPT, "late_fixture", "exec"), {})
    assert observed == [(False, False), (True, True)]


def test_late_fixture_never_moves_personal_codex_home(monkeypatch, tmp_path):
    executable = _late_fixture(monkeypatch, tmp_path, 1)
    home = tmp_path / ".codex"
    home.mkdir()
    marker = home / "preserved-file"
    marker.write_text("original fixture state")
    rename = Path.rename

    def restore(path, target):
        assert path != home
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", restore)
    with pytest.raises(SystemExit, match="late_harness_setup_failed"):
        exec(compile(_LATE_HARNESS_SCRIPT, "late_fixture", "exec"), {})
    assert executable.exists()
    assert marker.read_text() == "original fixture state"


def test_native_probe_timeout_names_recovery_after_restoration(monkeypatch, tmp_path):
    executable = _late_fixture(monkeypatch, tmp_path, 0)

    def run(argv, **kwargs):
        if not kwargs.get("shell"):
            raise subprocess.TimeoutExpired(argv, 60)
        return CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SystemExit, match="late_harness_discovery_failed"):
        exec(compile(_LATE_HARNESS_SCRIPT, "late_fixture", "exec"), {})
    assert executable.exists()


def test_machine_only_late_discovery_accepts_permissions_without_project_hooks(
    monkeypatch, tmp_path
):
    executable = _late_fixture(monkeypatch, tmp_path, 0)
    exec(compile(_LATE_HARNESS_SCRIPT, "late_fixture", "exec"), {})
    assert executable.exists()
    fixture_home = tmp_path / "late-codex"
    assert (fixture_home / "config.toml").is_file()
    assert not (fixture_home / "hooks.json").exists()
    assert not executable.with_name("codex.installer-qa-saved").exists()


@pytest.mark.parametrize(
    "scenario",
    [
        "harness-auth-missing",
        "dashboard-stale",
        "session-hook-unobserved",
        "foreign-install-binding",
        "guidance-unknown",
        "instruction-pointer-missing",
        "machine-unregistered",
        "resident-stale",
    ],
)
def test_install_health_scripted_failures_remain_diagnosed(
    monkeypatch, capsys, scenario
):
    from yoke_core.domain.installer_campaign_install_health_cases import (
        INSTALL_HEALTH_FAILURE_SCRIPT,
    )

    monkeypatch.setattr(sys, "argv", ["install-health-fixture", scenario])
    exec(
        compile(INSTALL_HEALTH_FAILURE_SCRIPT, "install-health-fixture", "exec"),
        {"scenario": scenario},
    )
    assert "diagnosed recovery verified" in capsys.readouterr().out


def test_issue_sync_probe_checks_installed_value_and_permission_refusal(
    monkeypatch, capsys
):
    import json
    from yoke_core.domain.installer_campaign_issue_sync_cases import (
        ISSUE_SYNC_DEFAULT_SCRIPT,
    )

    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert argv[0] == "fixture-yoke"
        if "create" in argv:
            return CompletedProcess(argv, 0, stdout=json.dumps({"success": True}))
        if "update" in argv:
            return CompletedProcess(
                argv,
                1,
                stdout=json.dumps(
                    {
                        "success": False,
                        "error": {"message": "active, verified binding required"},
                    }
                ),
            )
        assert argv[-3:] == ["--field", "github_sync_mode", "--json"]
        return CompletedProcess(
            argv,
            0,
            stdout=json.dumps({"success": True, "result": {"value": "disabled"}}),
        )

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", ["probe", "fixture-yoke"])
    exec(compile(ISSUE_SYNC_DEFAULT_SCRIPT, "issue-sync-probe", "exec"), {})
    assert len(calls) == 4
    assert "deliberate unbound enable refused" in capsys.readouterr().out


@pytest.mark.parametrize("failure", [None, "installer", "backup", "preparation"])
def test_hosted_ready_marker_follows_successful_exit_and_real_backup_check(
    monkeypatch,
    tmp_path,
    failure,
):
    from yoke_core.domain import installer_campaign_regression_cases as recipes

    backup = shlex.quote(str(tmp_path / "backup.tar"))
    installer = tmp_path / "installer.sh"
    installer.write_text(
        "printf '\\033[2Jinstaller TUI exited\\n'; "
        + (
            "exit 7"
            if failure == "installer"
            else f"rm {backup}"
            if failure == "backup"
            else "exit 0"
        )
    )
    monkeypatch.setattr(
        recipes, "PUBLIC_INSTALL", f"/bin/sh {shlex.quote(str(installer))}"
    )
    case = recipes._hosted_case(
        1,
        "backup-journey",
        "false"
        if failure == "preparation"
        else f"printf backup > {backup}; test -s {backup}",
        instructions="Preserve backup through hosted install.",
        outcome="Ready after exit.",
        after_installer=f"test -s {backup}",
    )
    result = subprocess.run(
        ["/bin/sh", "-c", case["entry_surface"]], capture_output=True, text=True
    )
    if failure:
        assert result.returncode != 0
        assert "backup-journey-ready" not in result.stdout
    else:
        assert result.returncode == 0
        visible = result.stdout.rsplit("\x1b[2J", 1)[-1]
        assert "backup-journey-prepared" in visible
        assert "backup-journey-ready" in visible
    assert case["method_config"]["actions"][-1]["ready_text"] == [
        "backup-journey-ready"
    ]
