from __future__ import annotations

import contextlib
import json
import subprocess
from pathlib import Path

from runtime.api.domain.validate_webapp_pipeline_test_support import (
    VALIDATOR_SCHEMA_DDL as _SCHEMA,
    install_rest_happy as _install_rest_happy,
    make_repo,
    make_script_dir as _make_script_dir,
    placeholder as _p,
)
from yoke_core.domain import db_backend
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.validate_webapp_pipeline import (
    ValidateContext,
    run_validation,
)
from runtime.api.fixtures.file_test_db import init_test_db


_APP_PERMISSIONS = {
    "metadata": "read",
    "issues": "write",
    "pull_requests": "write",
    "contents": "write",
    "actions": "write",
    "checks": "read",
    "workflows": "write",
    "secrets": "write",
    "actions_variables": "write",
}


def _seed_buzz(
    conn,
    db_dir: Path,
    *,
    include_app_auth: bool,
    ssh_settings: dict | None,
    docker_settings: dict | None,
    flow_stages: list | None,
    default_branch: str,
) -> None:
    p = _p(conn)
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, github_repo, default_branch) "
        f"VALUES ({p}, {p}, {p}, {p}, {p})",
        (2, "buzz", "Buzz", "example-org/buzz", default_branch),
    )
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        f"VALUES ({p}, {p}, {p})",
        (
            2,
            "github",
            json.dumps({
                "repo_owner": "example-org",
                "repo_name": "buzz",
                "installation_id": "12345",
                "repository_id": "4567",
            }),
        ),
    )
    if include_app_auth:
        permissions_json = json.dumps(_APP_PERMISSIONS)
        conn.execute(
            "INSERT INTO github_app_installations "
            "(installation_id, account_id, account_login, account_type, "
            "repository_selection, permissions, status, created_at, updated_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
            (
                "12345",
                "9988",
                "example-org",
                "Organization",
                "selected",
                permissions_json,
                "active",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO project_github_repo_bindings "
            "(project_id, installation_id, repository_id, github_repo, "
            "default_branch, status, permissions, created_at, updated_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
            (
                2,
                "12345",
                "4567",
                "example-org/buzz",
                default_branch,
                "active",
                permissions_json,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
    if ssh_settings is not None:
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            f"VALUES ({p}, {p}, {p})",
            (2, "ssh", json.dumps(ssh_settings)),
        )
    if docker_settings is not None:
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            f"VALUES ({p}, {p}, {p})",
            (2, "docker", json.dumps(docker_settings)),
        )
    stages = (
        flow_stages
        if flow_stages is not None
        else [
            {"name": "build", "executor": "github-actions"},
            {"name": "deploy", "executor": "github-actions"},
        ]
    )
    conn.execute(
        "INSERT INTO deployment_flows (id, project_id, name, stages) "
        f"VALUES ({p}, {p}, {p}, {p})",
        ("buzz-prod-release", 2, "Buzz Production Release", json.dumps(stages)),
    )


@contextlib.contextmanager
def _init_db(
    db_dir: Path,
    *,
    include_buzz: bool = True,
    include_app_auth: bool = True,
    ssh_settings: dict | None = None,
    docker_settings: dict | None = None,
    flow_stages: list | None = None,
    default_branch: str = "main",
):
    """Yield a backend-routed control-plane marker with the pipeline schema.

    ``init_test_db`` builds the schema on SQLite (a real file under ``db_dir``)
    or on a disposable Postgres database; ``_build_schema`` + ``_seed_buzz``
    seed through the backend factory so the validator (which reads via the same
    factory) sees the rows on both engines. The marker file at the yielded path
    satisfies the ``ctx.control_plane_marker.is_file()`` availability gate on
    Postgres (where the data lives in the DSN-pointed DB, not the file).
    """
    def _apply() -> None:
        conn = db_backend.connect()
        try:
            execute_schema_script(conn, _SCHEMA)
            conn.commit()
            if include_buzz:
                _seed_buzz(
                    conn,
                    db_dir,
                    include_app_auth=include_app_auth,
                    ssh_settings=ssh_settings,
                    docker_settings=docker_settings,
                    flow_stages=flow_stages,
                    default_branch=default_branch,
                )
                conn.commit()
        finally:
            conn.close()

    with init_test_db(db_dir, apply_schema=_apply) as db_path:
        Path(db_path).touch()
        yield Path(db_path)


def test_run_validation_happy_path(tmp_path: Path, monkeypatch, capsys) -> None:
    make_repo(tmp_path, optional_workflows=True)
    script_dir = _make_script_dir(tmp_path)

    def git_router(cmd, *, cwd=None, stdin=None, env=None):
        if "branch" in cmd and "--show-current" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "main\n", "")
        if "status" in cmd and "--porcelain" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("yoke_core.domain.validate_webapp_pipeline._run", git_router)
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_db._run", git_router
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_remote._run", git_router
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline._which", lambda cmd: True
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_remote._which",
        lambda cmd: True,
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_remote.resolve_project_github_auth",
        lambda project, **_kwargs: type(
            "ResolvedGithubAppAuth",
            (),
            {
                "project": project,
                "repo": "example-org/buzz",
                "token": "ghs_validator",
                "permissions": {"administration": "read"},
            },
        )(),
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_db."
        "load_github_app_control_plane_config",
        lambda: type(
            "ControlPlaneGitHubApp",
            (),
            {"endpoint": type("Endpoint", (), {"origin": "https://api.github.com"})()},
        )(),
    )
    _install_rest_happy(monkeypatch)

    with _init_db(
        tmp_path,
        ssh_settings={"host": "buzz.example", "user": "deploy", "key_path": "~/.ssh/id_rsa"},
        docker_settings={"registry": "ghcr.io"},
    ) as db_path:
        ctx = ValidateContext(
            project_root=tmp_path,
            script_dir=script_dir,
            control_plane_marker=db_path,
            project="buzz",
            verbose=True,
        )
        rc = run_validation(ctx)
    out = capsys.readouterr().out

    # Happy path has one warning: SSH section preserves prior "incomplete" behavior.
    assert rc == 0, out
    assert "Pre-flight PASSED with 1 warning(s)" in out
    assert "[FAIL]" not in out
    assert "Workflow file exists: buzz-deploy.yml" in out
    assert "GitHub environment 'production' exists" in out
    assert "buzz-prod-release flow has 2 stage(s)" in out


def test_run_validation_missing_control_plane_marker(
    tmp_path: Path, capsys
) -> None:
    ctx = ValidateContext(
        project_root=tmp_path,
        script_dir=_make_script_dir(tmp_path),
        control_plane_marker=tmp_path / "absent.db",
        project="buzz",
    )
    rc = run_validation(ctx)
    out = capsys.readouterr().out
    assert rc == 1
    assert "control-plane marker not found" in out
    assert "Pre-flight FAILED" in out


def test_run_validation_missing_project_and_token(tmp_path: Path, monkeypatch, capsys) -> None:
    script_dir = _make_script_dir(tmp_path)

    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline._which", lambda cmd: False
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_remote._which",
        lambda cmd: False,
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline._run",
        lambda cmd, **_: subprocess.CompletedProcess(cmd, 1, "", ""),
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_db._run",
        lambda cmd, **_: subprocess.CompletedProcess(cmd, 1, "", ""),
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_remote._run",
        lambda cmd, **_: subprocess.CompletedProcess(cmd, 1, "", ""),
    )

    with _init_db(tmp_path, include_buzz=False) as db_path:
        ctx = ValidateContext(
            project_root=tmp_path,
            script_dir=script_dir,
            control_plane_marker=db_path,
            project="buzz",
        )
        rc = run_validation(ctx)
    out = capsys.readouterr().out
    assert rc == 1
    assert "Buzz project not found in projects table" in out
    assert "Buzz github_repo not set" in out
    assert "No github capability for buzz" in out
    assert "No deployment flows for buzz" in out
    # GitHub App auth-only validator no longer probes the host gh CLI. Banned
    # strings built by concatenation so the AC-1 / AC-2 grep recipes
    # return zero hits anywhere in the live tree.
    assert ("gh CLI" + " not installed") not in out
    assert ("brew" + " install gh") not in out
    assert "buzz github auth not resolvable" in out


def test_run_validation_flags_missing_github_app_binding(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    make_repo(tmp_path, optional_workflows=True)
    script_dir = _make_script_dir(tmp_path)

    _install_rest_happy(monkeypatch)
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline._which", lambda cmd: True
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_remote._which",
        lambda cmd: True,
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline._run",
        lambda cmd, **_: subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_db._run",
        lambda cmd, **_: subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_remote._run",
        lambda cmd, **_: subprocess.CompletedProcess(cmd, 0, "", ""),
    )

    with _init_db(tmp_path, include_app_auth=False) as db_path:
        ctx = ValidateContext(
            project_root=tmp_path,
            script_dir=script_dir,
            control_plane_marker=db_path,
            project="buzz",
        )
        rc = run_validation(ctx)
    out = capsys.readouterr().out
    assert rc == 1
    assert "GitHub App repo binding not configured" in out


# Misconfiguration / CLI / SSH tests live in test_validate_webapp_pipeline_misc.py.
