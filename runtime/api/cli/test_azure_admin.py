"""Azure credentials stay local; each CLI call uses an isolated login."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts import azure_admin as admin
from yoke_contracts import azure_cli_prerequisite as prerequisite
from yoke_contracts.machine_config.capability_secret_store import (
    store_machine_capability_secret,
    read_machine_capability_secret,
)
from yoke_cli.commands.adapters import azure


pytestmark = pytest.mark.windows

SETTINGS = {
    "tenant_id": "tenant",
    "client_id": "client",
    "subscription_id": "subscription",
}


@pytest.fixture
def credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    path = store_machine_capability_secret(
        "project", "azure-admin", "client_secret", "test-secret"
    )
    monkeypatch.setattr(
        admin, "check_azure_cli", lambda: prerequisite.AzureCli(("az",), "test")
    )
    return path


def test_session_uses_private_cache_and_removes_it(credentials, monkeypatch):
    monkeypatch.setenv("AZURE_CONFIG_DIR", "ambient-account-cache")
    monkeypatch.setenv("ARM_CLIENT_SECRET", "ambient-secret")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert "ARM_CLIENT_SECRET" not in kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with admin.azure_session("project", SETTINGS, run=run) as (command, env):
        cache = Path(env["AZURE_CONFIG_DIR"])
        assert cache.is_dir() and str(cache) != "ambient-account-cache"
        assert command == ("az",)
        assert calls[0][0] == [
            "az",
            "login",
            "--service-principal",
            "--username",
            "client",
            "--password=test-secret",
            "--tenant",
            "tenant",
            "--output",
            "none",
        ]
        assert calls[1][0] == ["az", "account", "set", "--subscription", "subscription"]
    assert not cache.exists()
    assert (
        read_machine_capability_secret("project", "azure-admin", "client_secret")
        == "test-secret"
    )


@pytest.mark.parametrize("failure", ["denied", "timeout"])
def test_login_failure_never_discloses_secret(credentials, failure):
    caches = []

    def run(argv, **kwargs):
        caches.append(Path(kwargs["env"]["AZURE_CONFIG_DIR"]))
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 60)
        return SimpleNamespace(returncode=1, stdout="", stderr="denied test-secret")

    with pytest.raises(admin.AzureAdminError) as error:
        with admin.azure_session("project", SETTINGS, run=run):
            pytest.fail("login should refuse")
    assert "test-secret" not in str(error.value)
    assert not caches[0].exists()


def test_status_reports_missing_credentials_without_login(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.setattr(azure, "_project", lambda _: "project")
    monkeypatch.setattr(azure, "_settings", lambda _: SETTINGS)
    assert azure.azure_admin_status(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert not report["ready"]
    assert report["missing"] == ["client_secret"]


def test_admin_status_checks_selected_identity(credentials, monkeypatch, capsys):
    monkeypatch.setattr(azure, "_project", lambda _: "project")
    monkeypatch.setattr(azure, "_settings", lambda _: SETTINGS)

    def run(argv, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"id": "subscription", "tenantId": "tenant", "user": {"name": "client"}}
            ),
            stderr="",
        )

    # The real context uses its default runner, so replace just that injectable call.
    original = admin.azure_session
    monkeypatch.setattr(
        azure, "azure_session", lambda *a, **kw: original(*a, run=run, **kw)
    )
    monkeypatch.setattr(azure.subprocess, "run", run)
    assert azure.azure_admin_status(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True


def test_exec_preserves_child_exit_status_and_cleans_cache(credentials, monkeypatch):
    monkeypatch.setattr(azure, "_project", lambda _: "project")
    monkeypatch.setattr(azure, "_settings", lambda _: SETTINGS)
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        return SimpleNamespace(
            returncode=17 if argv[1] == "vm" else 0, stdout="", stderr=""
        )

    original = admin.azure_session
    monkeypatch.setattr(
        azure, "azure_session", lambda *a, **kw: original(*a, run=run, **kw)
    )
    monkeypatch.setattr(azure.subprocess, "run", run)
    assert azure.azure_exec(["--", "vm", "show", "--ids", "vm-id"]) == 17
    assert calls[-1][0] == ["az", "vm", "show", "--ids", "vm-id"]
    assert not Path(calls[-1][1]["env"]["AZURE_CONFIG_DIR"]).exists()


def test_cli_missing_and_unusable_name_install_recovery(monkeypatch):
    monkeypatch.setattr(prerequisite.shutil, "which", lambda _: None)
    monkeypatch.setattr(prerequisite.Path, "is_file", lambda _: False)
    with pytest.raises(
        prerequisite.AzureCliPrerequisiteError, match="azure-cli-missing.*install"
    ):
        prerequisite.check_azure_cli()
    monkeypatch.setattr(prerequisite.shutil, "which", lambda _: "az")
    monkeypatch.setattr(
        prerequisite.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1)
    )
    with pytest.raises(
        prerequisite.AzureCliPrerequisiteError, match="azure-cli-unusable.*repair"
    ):
        prerequisite.check_azure_cli()


def test_windows_install_off_path_is_named(monkeypatch):
    monkeypatch.setattr(prerequisite.shutil, "which", lambda _: None)
    monkeypatch.setattr(prerequisite.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        prerequisite.Path, "is_file", lambda p: str(p).endswith("az.cmd")
    )
    with pytest.raises(
        prerequisite.AzureCliPrerequisiteError, match="azure-cli-not-on-path.*az.cmd"
    ):
        prerequisite.check_azure_cli()


def test_old_serving_validator_names_provider_floor():
    from yoke_cli.commands.adapters.test_machine import _cloud_provider_floor
    from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError

    response = FunctionCallResponse(
        success=False,
        function="test_machine.settings_replace",
        version="v1",
        error=FunctionError(code="invalid_settings", message="unknown cloud_provider"),
    )
    error = _cloud_provider_floor(response).error
    assert error.code == "test_machine_cloud_provider_serving_floor_required"
    assert "minimum serving version next-release" in error.message
    assert "provider-capable serving build" in error.message


def test_windows_azure_cli_bypasses_batch_reparsing(monkeypatch, tmp_path):
    cli = tmp_path / "CLI2" / "wbin" / "az.cmd"
    cli.parent.mkdir(parents=True)
    cli.write_text("batch shim")
    python = cli.parent.parent / "python.exe"
    python.write_text("bundled interpreter")
    monkeypatch.setattr(prerequisite.shutil, "which", lambda _: str(cli))
    monkeypatch.setattr(prerequisite.platform, "system", lambda: "Windows")
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="azure-cli test")

    monkeypatch.setattr(prerequisite.subprocess, "run", run)
    assert prerequisite.check_azure_cli().command == (str(python), "-IBm", "azure.cli")
    assert calls == [[str(python), "-IBm", "azure.cli", "--version"]]
