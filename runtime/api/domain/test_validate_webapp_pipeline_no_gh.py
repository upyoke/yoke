"""App-backed REST validation without a host GitHub CLI."""

from __future__ import annotations

import contextlib
import json
import urllib.error
from pathlib import Path

from runtime.api.domain.validate_webapp_pipeline_test_support import (
    RestResponse as _RestResp,
    VALIDATOR_SCHEMA_DDL as _SCHEMA,
    fake_app_auth as _fake_app_auth,
    make_repo as _make_repo,
    patch_subprocess_helpers as _patch_subprocess_helpers,
    placeholder as _p,
)
from yoke_core.domain import db_backend
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.validate_webapp_pipeline import (
    ValidateContext,
    run_validation,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from runtime.api.fixtures.file_test_db import init_test_db


@contextlib.contextmanager
def _init_db(
    db_dir: Path,
    *,
    include_app_auth: bool = True,
):
    """Yield a backend-routed control-plane marker with the pipeline schema.

    ``init_test_db`` builds the schema on SQLite (a real file under ``db_dir``)
    or on a disposable Postgres database, and the seeds route through the
    backend factory so the validator sees them on both engines. The marker file
    at the yielded path satisfies the ``ctx.control_plane_marker.is_file()``
    availability gate on Postgres (data lives in the DSN-pointed DB, not the file).
    """
    def _apply() -> None:
        conn = db_backend.connect()
        try:
            execute_schema_script(conn, _SCHEMA)
            conn.commit()
            p = _p(conn)
            conn.execute(
                "INSERT INTO projects "
                "(id, slug, name, github_repo, default_branch) "
                f"VALUES ({p}, {p}, {p}, {p}, {p})",
                (
                    2, "externalwebapp", "ExternalWebapp", "example-org/externalwebapp", "main",
                ),
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
            if include_app_auth:
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
                        json.dumps({
                            "metadata": "read",
                            "issues": "write",
                            "pull_requests": "write",
                            "contents": "write",
                            "actions": "write",
                            "checks": "read",
                            "workflows": "write",
                            "secrets": "write",
                            "actions_variables": "write",
                        }),
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
                        "example-org/externalwebapp",
                        "main",
                        "active",
                        json.dumps({
                            "metadata": "read",
                            "issues": "write",
                            "pull_requests": "write",
                            "contents": "write",
                            "actions": "write",
                            "checks": "read",
                            "workflows": "write",
                            "secrets": "write",
                            "actions_variables": "write",
                        }),
                        "2026-01-01T00:00:00Z",
                        "2026-01-01T00:00:00Z",
                    ),
                )
            conn.execute(
                "INSERT INTO deployment_flows (id, project_id, name, stages) "
                f"VALUES ({p}, {p}, {p}, {p})",
                (
                    "managed-production", 2, "Production Release",
                    json.dumps([{"name": "deploy", "executor": "github-actions"}]),
                ),
            )
            conn.execute(
                "INSERT INTO project_structure "
                "(project_id, family, attachment_value, entry_key, payload) "
                f"VALUES ({p}, 'deploy_defaults', 'project', '', {p})",
                (2, json.dumps({"deployment_flow": "managed-production"})),
            )
            conn.commit()
        finally:
            conn.close()

    with init_test_db(db_dir, apply_schema=_apply) as db_path:
        Path(db_path).touch()
        yield Path(db_path)


def test_remote_validation_uses_app_backed_rest(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    _make_repo(tmp_path)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()

    _patch_subprocess_helpers(monkeypatch)

    seen: list[tuple[str, str]] = []
    seen_authorization: list[tuple[str, str | None]] = []

    def fake_urlopen(request, timeout):
        method = (getattr(request, "method", None) or request.get_method()).upper()
        path = request.full_url.split("api.github.com", 1)[-1]
        seen.append((method, path))
        seen_authorization.append((path, request.get_header("Authorization")))
        if "/actions/secrets" in path:
            return _RestResp(
                200,
                {
                    "secrets": [
                        {"name": "EXTERNALWEBAPP_SSH_KEY"},
                        {"name": "EXTERNALWEBAPP_SSH_HOST"},
                        {"name": "EXTERNALWEBAPP_SSH_USER"},
                    ]
                },
            )
        if "/environments" in path:
            return _RestResp(
                200, {"environments": [{"name": "production"}]},
            )
        return _RestResp(200, {})

    monkeypatch.setattr(
        "yoke_core.domain.gh_rest_transport.urlopen", fake_urlopen,
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_remote."
        "resolve_project_github_auth",
        lambda *_args, **_kwargs: _fake_app_auth(),
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

    with _init_db(tmp_path) as db_path:
        ctx = ValidateContext(
            project_root=tmp_path,
            script_dir=script_dir,
            control_plane_marker=db_path,
            project="externalwebapp",
        )
        rc = run_validation(ctx)
        out = capsys.readouterr().out
        full_permission_requests = list(seen)
        full_authorization = list(seen_authorization)

        monkeypatch.setattr(
            "yoke_core.domain.validate_webapp_pipeline_checks_remote."
            "resolve_project_github_auth",
            lambda *_args, **_kwargs: ProjectGithubAuth(
                project="externalwebapp",
                repo="example-org/externalwebapp",
                token="ghs_validator",
                installation_id="12345",
                permissions={},
            ),
        )
        seen.clear()
        seen_authorization.clear()
        limited_rc = run_validation(ctx)
        limited_out = capsys.readouterr().out
        limited_permission_requests = list(seen)
        limited_authorization = list(seen_authorization)

    assert rc == 0, out
    assert "GitHub secret exists: EXTERNALWEBAPP_SSH_KEY" in out
    assert "GitHub environment 'production' exists" in out
    # The validator should never degrade to host-CLI install guidance.
    assert ("gh CLI" + " installed") not in out
    assert ("gh CLI" + " not installed") not in out
    # Both REST endpoints were hit.
    assert any("/actions/secrets" in p for _m, p in full_permission_requests)
    assert any(p.endswith("/environments") for _m, p in full_permission_requests)
    assert all(auth == "Bearer ghs_validator" for _path, auth in full_authorization)
    assert limited_rc == 0, limited_out
    assert "Administration: Read permission is not granted" not in limited_out
    assert any("/actions/secrets" in p for _m, p in limited_permission_requests)
    assert any(
        p.endswith("/environments") for _m, p in limited_permission_requests
    )
    assert all(auth == "Bearer ghs_validator" for _path, auth in limited_authorization)


def test_remote_validation_no_app_auth_skips_rest_probes(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """When the canonical resolver yields no token, REST probes do not run."""
    _make_repo(tmp_path)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()

    _patch_subprocess_helpers(monkeypatch)

    def explode_urlopen(_request, _timeout):
        raise AssertionError("REST must not be called without App auth")

    monkeypatch.setattr(
        "yoke_core.domain.gh_rest_transport.urlopen", explode_urlopen,
    )

    with _init_db(tmp_path, include_app_auth=False) as db_path:
        ctx = ValidateContext(
            project_root=tmp_path,
            script_dir=script_dir,
            control_plane_marker=db_path,
            project="externalwebapp",
        )
        rc = run_validation(ctx)
    out = capsys.readouterr().out

    assert rc == 1
    assert "github auth not resolvable" in out
    assert "github-binding bind" in out
    # Crucially, the validator did NOT degrade to a host gh probe.
    # The validator should never degrade to host-CLI install guidance.
    assert ("gh CLI" + " not installed") not in out
    assert ("brew" + " install gh") not in out


def test_remote_validation_403_does_not_crash_validator(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """When the secrets endpoint returns 403 (e.g. permission shortfall), the
    validator surfaces "GitHub secret missing" FAILs but does not raise."""
    _make_repo(tmp_path)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()

    _patch_subprocess_helpers(monkeypatch)

    def fake_urlopen(request, timeout):
        path = request.full_url.split("api.github.com", 1)[-1]
        if "/actions/secrets" in path:
            raise urllib.error.HTTPError(
                url=request.full_url,
                code=403,
                msg="Forbidden - required GitHub App permission missing",
                hdrs=None,
                fp=None,
            )
        if "/environments" in path:
            return _RestResp(
                200, {"environments": [{"name": "production"}]},
            )
        return _RestResp(200, {})

    monkeypatch.setattr(
        "yoke_core.domain.gh_rest_transport.urlopen", fake_urlopen,
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_remote."
        "resolve_project_github_auth",
        lambda *_args, **_kwargs: _fake_app_auth(),
    )

    with _init_db(tmp_path) as db_path:
        ctx = ValidateContext(
            project_root=tmp_path,
            script_dir=script_dir,
            control_plane_marker=db_path,
            project="externalwebapp",
        )
        rc = run_validation(ctx)
    out = capsys.readouterr().out

    assert rc == 1
    # Each expected secret surfaces a FAIL with the bootstrap remediation.
    for name in (
        "EXTERNALWEBAPP_SSH_KEY",
        "EXTERNALWEBAPP_SSH_HOST",
        "EXTERNALWEBAPP_SSH_USER",
    ):
        assert f"GitHub secret missing: {name}" in out
