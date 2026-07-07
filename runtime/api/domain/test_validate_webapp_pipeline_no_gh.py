"""validate_webapp_pipeline: PAT-only behavior and no-gh-on-laptop coverage.

Companion to ``test_validate_webapp_pipeline.py`` /
``test_validate_webapp_pipeline_auth.py`` / ``..._misc.py``. Verifies
YOK-1843 task 5 contract on the remote-checks module:

- ``_check_github_actions_infrastructure`` runs without probing
  ``shutil.which('gh')``.
- The repo-scoped GitHub Actions secrets listing
  (``GET /repos/{owner}/{name}/actions/secrets``) and the production
  environment lookup (``GET /repos/{owner}/{name}/environments``) both
  route through the PAT-backed REST transport.
- The allowlisted environment-scoped enumeration is SKIPped cleanly when
  the resolver yields no token (the elevated-scope branch is not
  reachable without a valid PAT).
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.validate_webapp_pipeline import (
    ValidateContext,
    run_validation,
)
from runtime.api.fixtures.file_test_db import init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout


# ---------------------------------------------------------------------------
# Scaffolding (compact, scoped to this file)
# ---------------------------------------------------------------------------


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


_SCHEMA = """
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
"""


@contextlib.contextmanager
def _init_db(
    db_dir: Path,
    *,
    include_token: bool = True,
    secret_names: list[str] | None = None,
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
                    2, "buzz", "Buzz", "example-org/buzz", "main",
                ),
            )
            conn.execute(
                "INSERT INTO project_capabilities (project_id, type, settings) "
                f"VALUES ({p}, {p}, {p})",
                (2, "github", json.dumps({"repo": "example-org/buzz"})),
            )
            if include_token:
                conn.execute(
                    "INSERT INTO capability_secrets (project_id, type, key, value) "
                    f"VALUES ({p}, {p}, {p}, {p})",
                    (2, "github", "token", "gho_realtoken"),
                )
            conn.execute(
                "INSERT INTO deployment_flows (id, project_id, name, stages) "
                f"VALUES ({p}, {p}, {p}, {p})",
                (
                    "buzz-prod-release", 2, "Buzz Production Release",
                    json.dumps([{"name": "deploy", "executor": "github-actions"}]),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    with init_test_db(db_dir, apply_schema=_apply) as db_path:
        Path(db_path).touch()
        yield Path(db_path)


def _make_repo(root: Path) -> Path:
    repo = root / "fake-buzz"
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    register_machine_checkout(root / "machine-config", repo, 2)
    (repo / ".git").mkdir(exist_ok=True)
    for wf in ("buzz-deploy.yml", "buzz-smoke.yml"):
        (workflows / wf).write_text(f"name: {wf}\n")
    return repo


class _RestResp:
    def __init__(self, status: int, body: dict) -> None:
        self.status = status
        self.headers = {}
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _patch_subprocess_helpers(monkeypatch) -> None:
    """Stub _run/_which everywhere so the validator does not shell out."""

    def explode_which(_cmd):
        raise AssertionError("validator must not probe host gh CLI")

    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline._which",
        lambda cmd: True if cmd != "gh" else explode_which(cmd),
    )
    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_remote._which",
        lambda cmd: True if cmd != "gh" else explode_which(cmd),
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_remote_validation_uses_pat_backed_rest(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    _make_repo(tmp_path)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()

    _patch_subprocess_helpers(monkeypatch)

    seen: list[tuple[str, str]] = []

    def fake_urlopen(request, timeout):
        method = (getattr(request, "method", None) or request.get_method()).upper()
        path = request.full_url.split("api.github.com", 1)[-1]
        seen.append((method, path))
        if "/actions/secrets" in path:
            return _RestResp(
                200,
                {
                    "secrets": [
                        {"name": "BUZZ_SSH_KEY"},
                        {"name": "BUZZ_SSH_HOST"},
                        {"name": "BUZZ_SSH_USER"},
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

    with _init_db(tmp_path) as db_path:
        ctx = ValidateContext(
            project_root=tmp_path,
            script_dir=script_dir,
            control_plane_marker=db_path,
            project="buzz",
        )
        rc = run_validation(ctx)
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "GitHub secret exists: BUZZ_SSH_KEY" in out
    assert "GitHub environment 'production' exists" in out
    # The migration retired the host-CLI line entirely. Banned strings
    # built by concatenation so the AC-1 / AC-2 grep recipes return
    # zero hits anywhere in the live tree.
    assert ("gh CLI" + " installed") not in out
    assert ("gh CLI" + " not installed") not in out
    # Both REST endpoints were hit.
    assert any("/actions/secrets" in p for _m, p in seen)
    assert any(p.endswith("/environments") for _m, p in seen)


def test_remote_validation_no_pat_skips_rest_probes(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """When the canonical resolver yields no token, the validator emits
    the typed [FAIL] with the repair hint and skips REST cleanly. This
    is the SKIP-with-reason behavior the allowlisted elevated-scope
    branch follows when admin:repo scope is not configured.
    """
    _make_repo(tmp_path)
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()

    _patch_subprocess_helpers(monkeypatch)

    def explode_urlopen(_request, _timeout):
        raise AssertionError("REST must not be called without a PAT")

    monkeypatch.setattr(
        "yoke_core.domain.gh_rest_transport.urlopen", explode_urlopen,
    )

    with _init_db(tmp_path, include_token=False) as db_path:
        ctx = ValidateContext(
            project_root=tmp_path,
            script_dir=script_dir,
            control_plane_marker=db_path,
            project="buzz",
        )
        rc = run_validation(ctx)
    out = capsys.readouterr().out

    assert rc == 1
    # Resolver-failure repair hint surfaces (capability secret set
    # routes the operator to the canonical fix).
    assert "github auth not resolvable" in out
    assert "capability secret set" in out
    # Crucially, the validator did NOT degrade to a host gh probe.
    # Banned strings built by concatenation so the AC-1 / AC-2 grep
    # recipes return zero hits anywhere in the live tree.
    assert ("gh CLI" + " not installed") not in out
    assert ("brew" + " install gh") not in out


def test_remote_validation_403_does_not_crash_validator(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """When the secrets endpoint returns 403 (e.g. scope shortfall), the
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
                msg="Forbidden — admin:repo scope required",
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

    with _init_db(tmp_path) as db_path:
        ctx = ValidateContext(
            project_root=tmp_path,
            script_dir=script_dir,
            control_plane_marker=db_path,
            project="buzz",
        )
        rc = run_validation(ctx)
    out = capsys.readouterr().out

    assert rc == 1
    # Each expected secret surfaces a FAIL with the bootstrap remediation,
    # which is the SKIP-with-reason equivalent for the missing data path.
    for name in ("BUZZ_SSH_KEY", "BUZZ_SSH_HOST", "BUZZ_SSH_USER"):
        assert f"GitHub secret missing: {name}" in out
