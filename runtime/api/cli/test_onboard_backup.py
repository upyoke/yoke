"""Restore ordering, validation, and retry contracts for setup backups."""

from types import SimpleNamespace

import pytest

from yoke_cli.config import onboard_backup as backup
from yoke_cli.config import onboard_self_host_server as server
from yoke_cli.config.onboard_destinations import DESTINATION_LOCAL
from yoke_cli.config.setup_run_facts import RunFacts


def shell(tmp_path):
    return SimpleNamespace(
        result=SimpleNamespace(
            config_path=str(tmp_path / "config.json"),
            env_name="local",
            destination=DESTINATION_LOCAL,
            admin_name=None,
        ),
        _run_facts=RunFacts(),
    )


def test_command_uses_product_entrypoint_and_config_without_printing_token(monkeypatch):
    calls = []
    monkeypatch.setenv("YOKE_SESSION_ID", "old-session")

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(backup.subprocess, "run", run)
    assert backup.command("/tmp/config.json", "universe", "validate", "/tmp/a.tar") == {
        "ok": True
    }
    argv, kwargs = calls[0]
    assert argv[1:3] == ["-m", "yoke_cli.main"]
    assert kwargs["env"]["YOKE_MACHINE_CONFIG_FILE"] == "/tmp/config.json"
    assert "YOKE_SESSION_ID" not in kwargs["env"]
    assert kwargs["capture_output"] and kwargs["timeout"] == 600


@pytest.mark.parametrize("stdout", ["not-json", "[]", '{"success": false}'])
def test_command_refuses_invalid_receipt(monkeypatch, stdout):
    monkeypatch.setattr(
        backup.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )
    with pytest.raises(backup.BackupSetupError, match="backup_"):
        backup.command("config", "universe", "validate", "archive")


def test_validation_requires_verified_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "command", lambda *a: {"ok": True})
    with pytest.raises(backup.BackupSetupError, match="backup_validation_incomplete"):
        backup.validate("config", str(tmp_path / "backup.tar"))


def test_local_restore_binds_owner_and_retry_does_not_reimport(tmp_path, monkeypatch):
    calls = []
    app = shell(tmp_path)
    app._self_host_setup = SimpleNamespace(raw_token="server-credential")

    def command(config, *args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True, "actor_id": 19}

    monkeypatch.setattr(backup, "command", command)
    backup.restore_local(app, "backup.tar")
    backup.restore_local(app, "backup.tar")
    assert [args[0] for args, _ in calls] == ["init", "--env", "--env", "--env"]
    assert calls[1][0] == (
        "--env",
        "local",
        "universe",
        "import",
        "backup.tar",
        "--yes",
    )
    assert "19" in calls[2][0]
    assert calls[2][1] == {"json_output": False}
    assert app.result.admin_name is None


def test_self_host_import_precedes_core_start_and_retry_reuses_credential(
    tmp_path, monkeypatch
):
    app = shell(tmp_path)
    setup = server.SelfHostSetup(directory=tmp_path / "server", config_path="config")
    calls = []
    monkeypatch.setattr(
        server,
        "check_docker_prerequisites",
        lambda: SimpleNamespace(executable="docker"),
    )
    monkeypatch.setattr(
        server, "_ensure_wizard_bundle", lambda setup: calls.append("bundle")
    )
    monkeypatch.setattr(
        backup,
        "command",
        lambda *a, **k: calls.append("import") or {"raw_token": "credential"},
    )
    monkeypatch.setattr(
        backup.runtime, "start_bundle", lambda **k: calls.append("start")
    )
    monkeypatch.setattr(
        server, "retry_connection", lambda setup: calls.append("connect")
    )
    backup.restore_server(app, setup, "backup.tar")
    backup.restore_server(app, setup, "backup.tar")
    assert calls == ["bundle", "import", "start", "connect", "start", "connect"]
    assert app.result.same_host_self_host
    assert app.result.self_host_directory == str(setup.directory)


def test_projects_uses_restored_local_authority(tmp_path, monkeypatch):
    app = shell(tmp_path)
    calls = []
    monkeypatch.setattr(
        backup.existing_project_lookup,
        "_call_local_function",
        lambda **kwargs: (
            calls.append(kwargs) or {"result": {"rows": [{"id": 12, "slug": "demo"}]}}
        ),
    )
    assert backup.projects(app)[0]["id"] == 12
    assert calls == [
        {
            "config_path": app.result.config_path,
            "function": "projects.list",
            "payload": {},
        }
    ]


def test_lost_import_receipt_refuses_to_repeat_import(tmp_path, monkeypatch):
    app = shell(tmp_path)
    calls = []

    def command(config, *args, **kwargs):
        calls.append(args)
        raise backup.BackupSetupError("backup_receipt_unreadable: inspect destination")

    monkeypatch.setattr(backup, "command", command)
    with pytest.raises(backup.BackupSetupError, match="backup_receipt_unreadable"):
        backup._import(app, "config", "universe", "import", "backup.tar")
    with pytest.raises(backup.BackupSetupError, match="backup_import_outcome_unknown"):
        backup._import(app, "config", "universe", "import", "backup.tar")
    assert len(calls) == 1
