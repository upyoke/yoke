"""Misconfiguration / CLI / SSH coverage for validate_webapp_pipeline."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.domain.validate_webapp_pipeline_test_support import (
    RestResponse as _RestResp,
    seed_deploy_default,
)
from yoke_core.domain.validate_webapp_pipeline import (
    Counters,
    ValidateContext,
    _check_ssh_connectivity,
    main,
    run_validation,
)

@pytest.fixture(autouse=True)
def _stub_github_rest_empty(monkeypatch):
    """Default empty GitHub REST stub; tests can override locally."""

    def fake_urlopen(request, timeout=30):  # noqa: ANN001
        url = request.full_url
        if "/actions/secrets" in url:
            return _RestResp(200, {"secrets": []})
        if url.endswith("/environments") or "/environments?" in url:
            return _RestResp(200, {"environments": []})
        return _RestResp(200, {})

    monkeypatch.setattr(
        "yoke_core.domain.gh_rest_transport.urlopen", fake_urlopen,
    )


# ---------------------------------------------------------------------------
# DB + filesystem scaffolding
# ---------------------------------------------------------------------------
_SEED_SCHEMA_DDL = """
    CREATE TABLE projects (
      id INTEGER PRIMARY KEY,
      slug TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      github_repo TEXT,
      default_branch TEXT,
      public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
    );
    CREATE TABLE project_capabilities (
      id INTEGER PRIMARY KEY,
      project_id INTEGER NOT NULL,
      type TEXT NOT NULL,
      settings TEXT DEFAULT '{}',
      UNIQUE(project_id, type)
    );
    CREATE TABLE capability_secrets (
      id INTEGER PRIMARY KEY,
      project_id INTEGER NOT NULL,
      type TEXT NOT NULL,
      key TEXT NOT NULL,
      value TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT 'literal' CHECK(source = 'literal'),
      UNIQUE(project_id, type, key)
    );
    CREATE TABLE deployment_flows (
      id TEXT PRIMARY KEY,
      project_id INTEGER NOT NULL,
      name TEXT NOT NULL,
      stages TEXT NOT NULL
    );
    CREATE TABLE project_structure (id INTEGER PRIMARY KEY,
      project_id INTEGER NOT NULL, family TEXT NOT NULL,
      attachment_value TEXT NOT NULL, attachment_kind TEXT NOT NULL DEFAULT '',
      entry_key TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL DEFAULT '{}');
"""


def _p(conn) -> str: return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_seed(
    conn,
    *,
    include_externalwebapp: bool = True,
    ssh_settings: dict | None = None,
    docker_settings: dict | None = None,
    flow_stages: list | None = None,
    default_branch: str = "main",
) -> None:
    """Apply the validator's inline schema + externalwebapp rows to a backend connection.

    Shared by :func:`_init_db` (SQLite file) and :func:`_seed_backend` (PG
    per-test DB).
    """
    execute_schema_script(conn, _SEED_SCHEMA_DDL)
    if include_externalwebapp:
        p = _p(conn)
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, github_repo, default_branch) "
            f"VALUES ({p}, {p}, {p}, {p}, {p})",
            (2, "externalwebapp", "ExternalWebapp", "example-org/externalwebapp", default_branch),
        )
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            f"VALUES ({p}, {p}, {p})",
            (
                2,
                "github",
                json.dumps({
                    "repo_owner": "example-org",
                    "repo_name": "externalwebapp",
                    "installation_id": "12345",
                    "repository_id": "4567",
                }),
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
            ("managed-production", 2, "Production Release", json.dumps(stages)),
        )
        seed_deploy_default(conn, 2, "managed-production")
    conn.commit()


def _init_db(db_path: Path, **kwargs) -> None:
    """Seed a SQLite marker file and the backend-routed control-plane rows.

    On Postgres the file satisfies the production
    ``control_plane_marker.is_file()`` guard; the code-under-test's
    factory-routed ``_connect`` reads land in the per-test PG DB seeded by
    :func:`_seed_backend`.
    """
    conn = sqlite3.connect(db_path)
    try:
        _apply_seed(conn, **kwargs)
    finally:
        conn.close()


def _seed_backend(**kwargs):
    """``apply_schema`` strategy for :func:`init_test_db` (PG-portability seam).

    On Postgres seed the inline schema + rows into the per-test disposable DB the
    factory-routed ``_connect`` reads. On SQLite a no-op (the seeded file IS it).
    """
    from yoke_core.domain import db_backend

    def _apply() -> None:
        conn = db_backend.connect()
        try:
            _apply_seed(conn, **kwargs)
        finally:
            conn.close()

    return _apply


def _make_externalwebapp_repo(root: Path, *, with_git: bool = True) -> Path:
    repo = root / "fake-externalwebapp"
    repo.mkdir(parents=True, exist_ok=True)
    register_machine_checkout(root / "machine-config", repo, 2)
    if with_git:
        (repo / ".git").mkdir(exist_ok=True)
        workflows = repo / ".github" / "workflows"
        workflows.mkdir(parents=True, exist_ok=True)
        (workflows / "externalwebapp-deploy.yml").write_text("name: deploy\n")
        (workflows / "externalwebapp-smoke.yml").write_text("name: smoke\n")
        (workflows / "externalwebapp-ephemeral.yml").write_text("name: eph\n")
        (workflows / "externalwebapp-ephemeral-teardown.yml").write_text("name: teardown\n")
    return repo


def _make_script_dir(root: Path) -> Path:
    script_dir = root / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    return script_dir


def _stub_which_and_run(monkeypatch) -> None:
    """Stub ``_which`` (always present) and ``_run`` (success) on every module
    namespace the validator monkeypatches, so no real gh/ssh subprocess runs."""
    ok = lambda cmd, **_: subprocess.CompletedProcess(cmd, 0, "", "")  # noqa: E731
    for mod in (
        "yoke_core.domain.validate_webapp_pipeline",
        "yoke_core.domain.validate_webapp_pipeline_checks_db",
        "yoke_core.domain.validate_webapp_pipeline_checks_remote",
    ):
        monkeypatch.setattr(f"{mod}._run", ok)
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline._which", lambda cmd: True
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_remote._which",
        lambda cmd: True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_validation_flags_missing_externalwebapp_repo(tmp_path: Path, monkeypatch, capsys) -> None:
    with init_test_db(tmp_path, apply_schema=_seed_backend()) as token:
        db_path = Path(token)
        _init_db(db_path)
        # Do NOT create the fake-externalwebapp directory.
        script_dir = _make_script_dir(tmp_path)
        _stub_which_and_run(monkeypatch)

        ctx = ValidateContext(
            project_root=tmp_path,
            script_dir=script_dir,
            control_plane_marker=db_path,
            project="externalwebapp",
        )
        rc = run_validation(ctx)
        out = capsys.readouterr().out
        assert rc == 1
        assert "Externalwebapp repo not found" in out


def test_run_validation_reports_python_pipeline_entrypoints(tmp_path: Path, monkeypatch, capsys) -> None:
    with init_test_db(tmp_path, apply_schema=_seed_backend()) as token:
        db_path = Path(token)
        _init_db(db_path)
        _make_externalwebapp_repo(tmp_path)
        script_dir = tmp_path / "scripts"
        script_dir.mkdir()
        _stub_which_and_run(monkeypatch)

        ctx = ValidateContext(
            project_root=tmp_path,
            script_dir=script_dir,
            control_plane_marker=db_path,
            project="externalwebapp",
        )
        rc = run_validation(ctx)
        out = capsys.readouterr().out
        assert rc == 1  # gh secret/env responses are empty in this test
        for module_name in (
            "yoke_core.domain.worktree",
            "yoke_core.engines.merge_worktree",
            "yoke_core.domain.projects",
            "yoke_core.domain.flow",
            "yoke_core.domain.deploy_pipeline",
            "yoke_core.domain.github_actions",
            "yoke_core.tools.executors",
        ):
            assert f"Python entrypoint exists: {module_name}" in out


def test_run_validation_bad_flow_stages_json(tmp_path: Path, monkeypatch, capsys) -> None:
    with init_test_db(
        tmp_path, apply_schema=_seed_backend(flow_stages=[])
    ) as token:
        db_path = Path(token)
        _init_db(db_path, flow_stages=[])  # empty list is still a valid list
        _make_externalwebapp_repo(tmp_path)
        script_dir = _make_script_dir(tmp_path)

        # Clobber the flow stages with invalid JSON to exercise the error
        # branch. Use the backend-aware connection so on Postgres the UPDATE
        # lands in the per-test DB the factory-routed code reads.
        conn = connect_test_db(db_path)
        try:
            conn.execute(
                "UPDATE deployment_flows SET stages='not-json' "
                "WHERE id='managed-production'"
            )
            conn.commit()
        finally:
            conn.close()

        _stub_which_and_run(monkeypatch)

        ctx = ValidateContext(
            project_root=tmp_path,
            script_dir=script_dir,
            control_plane_marker=db_path,
            project="externalwebapp",
        )
        rc = run_validation(ctx)
        out = capsys.readouterr().out
        assert rc == 1
        assert "managed-production flow not found, inactive, or has no stages" in out


def test_check_ssh_connectivity_preserves_prior_warning(capsys) -> None:
    """Section 6 reports the current advisory SSH config warning."""
    counters = Counters()
    ctx = ValidateContext(
        project_root=Path("/"),
        script_dir=Path("/"),
        control_plane_marker=Path("/nonexistent"),
        project="externalwebapp",
    )
    _check_ssh_connectivity(ctx, counters)
    out = capsys.readouterr().out
    assert counters.warned == 1
    assert "SSH config incomplete (host=, user=)" in out


def test_main_cli_forwards_exit_code(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "control-plane.marker"  # absent: forces failure
    argv = [
        "--verbose",
        "--project",
        "externalwebapp",
        "--project-root",
        str(tmp_path),
        "--script-dir",
        str(tmp_path),
        "--yoke-db",
        str(db_path),
    ]
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == 1
