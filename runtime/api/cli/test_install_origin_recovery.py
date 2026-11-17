"""Missing distribution metadata stays a repair step on every install surface."""

import importlib
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_cli.config import install_advice


@pytest.fixture(autouse=True)
def missing_origin(tmp_path, monkeypatch):
    monkeypatch.delenv("YOKE_INSTALL_BASE_URL", raising=False)
    monkeypatch.delenv("YOKE_MACHINE_HOME", raising=False)
    config = tmp_path / "config.json"
    config.write_text('{}')
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config))


def assert_repair(message, next_step):
    assert "install_origin_unavailable: restore settings.distribution.origin" in message
    assert "yoke settings set distribution" in message
    assert "`install_origin_unavailable" not in message
    assert next_step in message


def test_managed_hooks_import_and_render_lazily(monkeypatch, tmp_path):
    from yoke_cli.project_install import managed_git_hooks as hooks

    with monkeypatch.context() as patch:
        patch.setattr(install_advice, "install_command", Mock(side_effect=AssertionError))
        importlib.reload(hooks)  # Import must never resolve install authority.
    importlib.reload(hooks)
    for spec in hooks.managed_git_hook_specs():
        assert_repair(spec["content"], "then install Yoke")
        subprocess.run(["sh", "-n"], input=spec["content"], text=True, check=True)
        result = subprocess.run(
            ["sh"], input=spec["content"], text=True, capture_output=True,
            env={"PATH": "/usr/bin:/bin", "XDG_BIN_HOME": str(tmp_path)}, check=True,
        )
        assert_repair(result.stderr, "then install Yoke")
        assert "not found" not in result.stderr


def test_native_windows_and_git_guidance():
    from yoke_cli.self_host.native_windows import NativeWindowsError
    from yoke_cli.config.project_git_install_advice import install_advice as git_advice

    assert_repair(str(NativeWindowsError()), "then install Yoke inside that distribution")
    assert_repair(git_advice(platform_name="win32").note, "then rerun the installer")


def test_update_recoveries(monkeypatch):
    from yoke_cli.config import self_update, update_check

    monkeypatch.setattr(self_update.install_binding, "require_packaged_install",
                        lambda *args: {"version": ""})
    for run, command in [(self_update.run_update, "yoke update"),
                         (update_check.run_check, "yoke update --check")]:
        with pytest.raises(self_update.SelfUpdateError) as refused:
            run()
        assert_repair(str(refused.value), f"before running `{command}`")


def test_relay_parser_startup_and_standalone_launcher(tmp_path, monkeypatch):
    from yoke_core.tools import install_yoke_launcher as launcher
    from yoke_core.tools.install_yoke_launcher_core import write_launcher
    from yoke_core.tools.session_relay_local_install import local_launcher_recovery
    from yoke_core.domain import main_agent_packet

    assert_repair(local_launcher_recovery(), "retry the relay install")
    assert_repair(launcher._build_parser().description, "then install the release")
    monkeypatch.setattr(main_agent_packet.shutil, "which", lambda *args: None)
    assert_repair(main_agent_packet.render_install_advisory_block(), "then retry")
    target = tmp_path / "yoke"
    write_launcher(target)
    namespace = {}
    exec(compile(target.read_text(), str(target), "exec"), namespace)
    assert_repair(namespace["RELEASE_RECOVERY"], "then install the released CLI and retry")


def test_launcher_repair_without_candidate(tmp_path, monkeypatch):
    from yoke_core.tools import install_yoke_launcher_sweep as sweep

    monkeypatch.setattr(sweep, "verify_repo_root", lambda *args: None)
    monkeypatch.setattr(sweep, "canonical_shim_path", lambda *args: tmp_path / "yoke")
    monkeypatch.setattr(sweep, "refuse_foreign_binary", lambda *args, **kw: None)
    monkeypatch.setattr(sweep, "_candidate_interpreters", lambda *args: [])
    with pytest.raises(sweep.InstallError) as refused:
        sweep.repair_canonical_launcher(tmp_path)
    assert_repair(str(refused.value), "then retry --repair")


def test_git_pre_commit_missing_package(monkeypatch, capsys):
    import builtins
    from yoke_cli.commands import git_hook

    original = builtins.__import__

    def without_harness(name, *args, **kwargs):
        if name == "yoke_harness.git_hooks.pre_commit":
            raise ImportError("missing harness")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(git_hook, "_refresh_atlas_currency_or_skip", lambda: None)
    monkeypatch.setattr(builtins, "__import__", without_harness)
    assert git_hook.git_pre_commit([]) == 1
    assert_repair(capsys.readouterr().err, "then repair the machine CLI")


def test_wizard_missing_required_tool(monkeypatch):
    from yoke_cli.config import onboard_wizard_path as wizard

    monkeypatch.setattr(wizard.path_doctor, "diagnose",
                        lambda: SimpleNamespace(future_resolved=[]))
    monkeypatch.setattr(wizard.path_repair_plan, "build", lambda *args: {})
    _, message = wizard.PathFlow._check_install(SimpleNamespace())
    assert_repair(message, "then run the installer again")


def test_doctor_missing_launcher(tmp_path, monkeypatch):
    from yoke_core.engines import doctor_hc_launcher_authority as doctor
    from yoke_cli.config import path_doctor

    monkeypatch.setattr(doctor, "canonical_shim_path", lambda: tmp_path / "yoke")
    monkeypatch.setattr(doctor, "_login_shell_yoke", lambda: "")
    monkeypatch.setattr(doctor, "enumerate_shadow_installs", lambda **kw: [])
    monkeypatch.setattr(doctor, "_resolve_checkout", lambda args: None)
    monkeypatch.setattr(path_doctor, "diagnose", lambda **kw: SimpleNamespace(contexts=[]))
    rec = Mock()
    doctor.hc_launcher_authority(None, SimpleNamespace(fix=False), rec)
    assert_repair(rec.record.call_args.args[3], "Then repair:")


def test_overview_activation_returns_null(monkeypatch):
    from yoke_core.domain import db_helpers, overview_activation_read
    from yoke_core.domain.handlers import overview_activation as overview

    monkeypatch.setattr(db_helpers, "connect", Mock(return_value=Mock()))
    monkeypatch.setattr(overview_activation_read, "compute_activation", lambda *args: {})
    monkeypatch.setattr(overview, "_actor_id", lambda *args: 1)
    outcome = overview.handle_overview_activation_get(SimpleNamespace(
        payload={}, target=SimpleNamespace(kind="global")
    ))
    assert outcome.primary_success
    assert outcome.result_payload["install_command"] is None
