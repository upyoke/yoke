"""Shared fixtures for webapp pipeline validator tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_contracts.github_origin import DEFAULT_GITHUB_API_URL
from yoke_core.domain import db_backend
from yoke_core.domain.project_github_auth import ProjectGithubAuth


VALIDATOR_SCHEMA_DDL = f"""
CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL, github_repo TEXT, default_branch TEXT,
  public_item_prefix TEXT NOT NULL DEFAULT 'YOK');
CREATE TABLE project_capabilities (id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL, type TEXT NOT NULL,
  settings TEXT DEFAULT '{{}}', UNIQUE(project_id, type));
CREATE TABLE capability_secrets (id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL, type TEXT NOT NULL, key TEXT NOT NULL,
  value TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'literal'
  CHECK(source = 'literal'), UNIQUE(project_id, type, key));
CREATE TABLE github_app_installations (
  installation_id TEXT PRIMARY KEY,
  api_url TEXT NOT NULL DEFAULT '{DEFAULT_GITHUB_API_URL}',
  account_id TEXT NOT NULL,
  account_login TEXT NOT NULL, account_type TEXT NOT NULL,
  repository_selection TEXT NOT NULL DEFAULT 'selected',
  permissions TEXT NOT NULL DEFAULT '{{}}', status TEXT NOT NULL DEFAULT 'active',
  last_verified_at TEXT, last_error TEXT, created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL);
CREATE TABLE project_github_repo_bindings (
  project_id INTEGER PRIMARY KEY,
  installation_id TEXT NOT NULL REFERENCES github_app_installations(installation_id),
  repository_id TEXT, api_url TEXT NOT NULL DEFAULT '{DEFAULT_GITHUB_API_URL}',
  github_repo TEXT NOT NULL, default_branch TEXT,
  status TEXT NOT NULL DEFAULT 'active', permissions TEXT NOT NULL DEFAULT '{{}}',
  last_verified_at TEXT, last_error TEXT, created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX uq_project_github_repo_bindings_installation_repository_id
ON project_github_repo_bindings(installation_id, repository_id);
CREATE TABLE deployment_flows (id TEXT PRIMARY KEY, project_id INTEGER NOT NULL,
  name TEXT NOT NULL, stages TEXT NOT NULL);
"""


class RestResponse:
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


def placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def install_rest_happy(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        url = request.full_url
        if "/actions/secrets" in url:
            names = ("BUZZ_SSH_KEY", "BUZZ_SSH_HOST", "BUZZ_SSH_USER")
            return RestResponse(200, {"secrets": [{"name": n} for n in names]})
        if url.endswith("/environments") or "/environments?" in url:
            return RestResponse(200, {"environments": [{"name": "production"}]})
        return RestResponse(200, {})

    monkeypatch.setattr("yoke_core.domain.gh_rest_transport.urlopen", fake_urlopen)


def make_repo(root: Path, *, optional_workflows: bool = False) -> Path:
    repo = root / "fake-buzz"
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    register_machine_checkout(root / "machine-config", repo, 2)
    (repo / ".git").mkdir(exist_ok=True)
    names = ["buzz-deploy.yml", "buzz-smoke.yml"]
    if optional_workflows:
        names += ["buzz-ephemeral.yml", "buzz-ephemeral-teardown.yml"]
    for name in names:
        (workflows / name).write_text(f"name: {name}\n")
    return repo


def make_script_dir(root: Path) -> Path:
    path = root / "scripts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def fake_app_auth(*, administration: bool = True) -> ProjectGithubAuth:
    permissions = {"administration": "read"} if administration else {}
    return ProjectGithubAuth(
        project="buzz", repo="example-org/buzz", token="ghs_validator",
        installation_id="12345",
        permissions=permissions,
    )


def patch_subprocess_helpers(monkeypatch) -> None:
    def explode_which(_cmd):
        raise AssertionError("validator must not probe host gh CLI")

    for module in (
        "yoke_core.domain.validate_webapp_pipeline",
        "yoke_core.domain.validate_webapp_pipeline_checks_remote",
    ):
        monkeypatch.setattr(
            f"{module}._which",
            lambda cmd: True if cmd != "gh" else explode_which(cmd),
        )
    for module in (
        "yoke_core.domain.validate_webapp_pipeline",
        "yoke_core.domain.validate_webapp_pipeline_checks_db",
        "yoke_core.domain.validate_webapp_pipeline_checks_remote",
    ):
        monkeypatch.setattr(
            f"{module}._run",
            lambda cmd, **_: subprocess.CompletedProcess(cmd, 0, "", ""),
        )


__all__ = [
    "RestResponse", "VALIDATOR_SCHEMA_DDL", "fake_app_auth",
    "install_rest_happy", "make_repo", "make_script_dir",
    "patch_subprocess_helpers", "placeholder",
]
