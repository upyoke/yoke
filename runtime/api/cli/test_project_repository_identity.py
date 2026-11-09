"""Checkout guards refuse mismatched repositories before product writes."""

from types import SimpleNamespace
import subprocess

import pytest

from yoke_cli import project_repository_identity as identity
from yoke_cli.commands.adapters import project_snapshot as snapshot
from yoke_cli.project_install import runner


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def origin(repo, value):
    subprocess.run(["git", "-C", str(repo), "config", "remote.origin.url", value], check=True)


@pytest.fixture
def bound(monkeypatch):
    monkeypatch.setattr(identity, "_binding_status", lambda *a, **k: {
        "github_repo": "example/widget", "api_url": "https://api.github.com",
    })


@pytest.mark.parametrize("remote", [
    "https://github.com/example/widget.git",
    "git@github.com:Example/Widget.git",
    "ssh://git@github.com/example/widget.git",
])
def test_matching_origins(repo, bound, remote):
    origin(repo, remote)
    identity.assert_project_repository(repo, "widget")


@pytest.mark.parametrize("remote", [
    "https://github.com/other/repo.git",
    "git@github.com:fork-owner/widget.git",
    "https://other.example/example/widget.git",
    "/some/local/repository",
    "https://secret@github.com/other/repo.git",
])
def test_mismatch_refuses_with_recovery_without_leaking_credentials(repo, bound, remote):
    origin(repo, remote)
    with pytest.raises(identity.ProjectRepositoryIdentityError) as error:
        identity.assert_project_repository(repo, "widget")
    assert "project_repository_mismatch" in str(error.value)
    assert "example/widget" in str(error.value)
    assert "Recovery:" in str(error.value)
    assert "secret" not in str(error.value)


def test_missing_origin_needs_no_binding_read(repo, monkeypatch):
    monkeypatch.setattr(identity, "_binding_status", lambda *a, **k: pytest.fail("network read"))
    identity.assert_project_repository(repo, "widget")


def test_unbound_project_accepts_any_origin(repo, monkeypatch):
    origin(repo, "git@github.com:other/repo.git")
    monkeypatch.setattr(identity, "_binding_status", lambda *a, **k: None)
    identity.assert_project_repository(repo, "local-project")


@pytest.mark.parametrize("head_only", [False, True])
def test_snapshot_cli_refuses_before_dispatch(repo, bound, monkeypatch, capsys, head_only):
    origin(repo, "git@github.com:other/repo.git")
    monkeypatch.setattr(snapshot, "_project_context", lambda _: "widget")
    monkeypatch.setattr(snapshot, "plan_sync", lambda *a, **k: SimpleNamespace(repo_root=repo))
    monkeypatch.setattr(snapshot, "sync_snapshots", lambda **k: pytest.fail("snapshot write"))
    monkeypatch.setattr(snapshot, "_dispatch_sync_payload", lambda **k: pytest.fail("head write"))
    assert snapshot.project_snapshot_sync([str(repo), *(["--head-only"] if head_only else [])]) == 1
    assert "project_repository_mismatch" in capsys.readouterr().err


def test_prewrite_sync_refuses_before_dispatch(repo, bound, monkeypatch):
    origin(repo, "git@github.com:other/repo.git")
    monkeypatch.setattr(snapshot, "_project_context", lambda _: "widget")
    monkeypatch.setattr(snapshot, "plan_sync", lambda *a, **k: SimpleNamespace(repo_root=repo))
    monkeypatch.setattr(snapshot, "sync_snapshots", lambda **k: pytest.fail("snapshot write"))
    result = snapshot.sync_local_snapshot_for_write(
        project="widget", repo_root=str(repo), integration_target=None, session_id=None,
    )
    assert result["status"] != "ok"
    assert "project_repository_mismatch" in result["message"]


def test_install_refuses_before_checkout_or_repository_changes(repo, bound, monkeypatch):
    origin(repo, "git@github.com:other/repo.git")
    monkeypatch.setattr(runner.source_dev, "resolve_mode", lambda *a: ("copy", "test"))
    monkeypatch.setattr(runner.git_hooks_layer, "assert_pre_commit_runtime_available", lambda: None)
    monkeypatch.setattr(runner, "_resolve_project_id", lambda *a: (42, True))
    monkeypatch.setattr(runner, "_resolve_bundle", lambda *a, **k: ({}, "test"))
    monkeypatch.setattr(runner, "validate_bundle_for_project", lambda *a: None)
    monkeypatch.setattr(runner.checkout_gate, "assert_ready_for_write", lambda *a, **k: pytest.fail("checkout write"))
    with pytest.raises(runner.ProjectInstallError, match="project_repository_mismatch"):
        runner.install(repo, 42)


def test_register_warns_without_binding_read(repo, monkeypatch, capsys):
    from yoke_cli.config import writer_projects as writer
    from yoke_cli.config import machine_config
    from runtime.api.domain.machine_config_writer_projects_test_support import _seed_https

    machine_home = repo / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    _seed_https(machine_home, repo)
    config = machine_home / "config.json"
    monkeypatch.setattr(identity, "_binding_status", lambda *a, **k: pytest.fail("network read"))
    writer.register_project(repo, 42, path=config)
    assert machine_config.project_id(repo, config) == 42
    assert "local routing only" in capsys.readouterr().err


def test_binding_read_failure_refuses_instead_of_accepting_origin(repo, monkeypatch):
    from yoke_cli.transport import dispatcher
    from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError

    origin(repo, "git@github.com:example/widget.git")
    monkeypatch.setattr(dispatcher, "call_dispatcher", lambda **k: FunctionCallResponse(
        success=False, function="projects.github_binding.status", version="v1",
        error=FunctionError(code="connection_unavailable", message="connection unavailable"),
    ))
    with pytest.raises(identity.ProjectRepositoryIdentityError, match="binding_unavailable"):
        identity.assert_project_repository(repo, "widget")


def test_binding_read_preserves_timeout_config_and_explicit_connection(repo, monkeypatch):
    import os
    from yoke_cli.transport import dispatcher
    from yoke_contracts.api.function_call import FunctionCallResponse
    from yoke_contracts.machine_config.paths import config_path

    origin(repo, "git@github.com:example/widget.git")
    selected = repo / "selected.json"
    observed = []

    def status(**kwargs):
        observed.append((kwargs, config_path(), os.environ.get("YOKE_ENV")))
        return FunctionCallResponse(
            success=True, function="projects.github_binding.status", version="v1",
            result={"binding": {"github_repo": "example/widget", "api_url": "https://api.github.com"}},
        )

    monkeypatch.setattr(dispatcher, "call_dispatcher", status)
    monkeypatch.setenv("YOKE_ENV", "previous")
    identity.assert_project_repository(
        repo, "widget", config_path=selected, explicit_env="selected", timeout_s=8,
    )
    kwargs, selected_path, env = observed[0]
    assert kwargs["function_id"] == "projects.github_binding.status"
    assert kwargs["payload"] == {"project": "widget"}
    assert kwargs["timeout_s"] == 8
    assert selected_path == selected
    assert env == "selected"
    assert os.environ["YOKE_ENV"] == "previous"
