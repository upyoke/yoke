"""validate_webapp_pipeline — canonical project github auth regressions.

Split out of ``test_validate_webapp_pipeline.py`` (formerly 315 lines)
so the authored file stays under the 350-line limit. Covers the
``MissingCapability`` / ``MissingAppCredentials`` translation path through
``_check_github_actions_infrastructure``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from yoke_core.domain import db_backend
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_core.domain.validate_webapp_pipeline import (
    ValidateContext,
    run_validation,
)
from yoke_core.domain.validate_webapp_pipeline_checks_remote import (
    _REMOTE_GITHUB_READ_PERMISSION_LEVELS,
    _check_github_actions_infrastructure,
)
from yoke_core.domain.validate_webapp_pipeline_helpers import Counters
from runtime.api.domain.validate_webapp_pipeline_test_support import fake_app_auth


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
"""


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_seed_minus_github(conn) -> None:
    """Apply schema + buzz row + flow but NO github capability/secret rows.

    Shared by the per-test authority seed and the assertions in this file.
    """
    execute_schema_script(conn, _SEED_SCHEMA_DDL)
    p = _p(conn)
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, github_repo, default_branch) "
        f"VALUES ({p}, {p}, {p}, {p}, {p})",
        (2, "buzz", "Buzz", "example-org/buzz", "main"),
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


def _touch_db_token(db_path: Path) -> None:
    """Create the marker needed by ``ctx.control_plane_marker.is_file()``."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.touch()


def _seed_backend_minus_github():
    """``apply_schema`` strategy for :func:`init_test_db` (PG-portability seam).

    repoints ``YOKE_PG_DSN`` at -- the same DB the factory-routed code reads.
    """
    from yoke_core.domain import db_backend

    def _apply() -> None:
        conn = db_backend.connect()
        try:
            _apply_seed_minus_github(conn)
        finally:
            conn.close()

    return _apply


def _make_buzz_repo(root: Path) -> Path:
    repo = root / "fake-buzz"
    repo.mkdir(parents=True, exist_ok=True)
    register_machine_checkout(root / "machine-config", repo, 2)
    (repo / ".git").mkdir(exist_ok=True)
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    for wf in ("buzz-deploy.yml", "buzz-smoke.yml"):
        (workflows / wf).write_text(f"name: {wf}\n")
    return repo


def test_canonical_resolver_missing_capability_translates_to_fail(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """No github capability row -> resolver raises MissingCapability.

    Section 3 emits a [FAIL] with the canonical App-binding repair hint,
    not the retired host-login instruction.
    """
    with init_test_db(tmp_path, apply_schema=_seed_backend_minus_github()) as token:
        db_path = Path(token)
        _touch_db_token(db_path)
        _make_buzz_repo(tmp_path)
        script_dir = tmp_path / "scripts"
        script_dir.mkdir(parents=True, exist_ok=True)

        def fake_run(cmd, *, cwd=None, stdin=None, env=None):
            # The resolver fails before any GitHub REST request; unrelated
            # local validation commands can return cleanly.
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(
            "yoke_core.domain.validate_webapp_pipeline._which", lambda _cmd: True
        )
        monkeypatch.setattr(
            "yoke_core.domain.validate_webapp_pipeline_checks_remote._which",
            lambda _cmd: True,
        )
        monkeypatch.setattr(
            "yoke_core.domain.validate_webapp_pipeline._run", fake_run
        )
        monkeypatch.setattr(
            "yoke_core.domain.validate_webapp_pipeline_checks_db._run", fake_run
        )
        monkeypatch.setattr(
            "yoke_core.domain.validate_webapp_pipeline_checks_remote._run",
            fake_run,
        )

        ctx = ValidateContext(
            project_root=tmp_path,
            script_dir=script_dir,
            control_plane_marker=db_path,
            project="buzz",
        )
        rc = run_validation(ctx)
        out = capsys.readouterr().out
        assert rc == 1
        # Canonical resolver text + repair hint surface in the check output.
        assert "github auth not resolvable" in out
        assert "no GitHub App capability row" in out
        assert "yoke projects github-binding bind --project buzz" in out
        retired_hint = "Run: gh " + "auth " + "login"
        assert retired_hint not in out


def test_remote_checks_reject_repo_projection_mismatch_before_io(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    marker = tmp_path / "control-plane"
    marker.touch()
    ctx = ValidateContext(
        project_root=tmp_path,
        script_dir=tmp_path / "scripts",
        control_plane_marker=marker,
        project="buzz",
    )
    def resolve_auth(*_args, **kwargs):
        assert (
            kwargs["required_permissions"]
            is _REMOTE_GITHUB_READ_PERMISSION_LEVELS
        )
        return fake_app_auth()

    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_remote."
        "resolve_project_github_auth",
        resolve_auth,
    )

    def unexpected_io(*_args, **_kwargs):
        raise AssertionError("repo mismatch must stop before GitHub I/O")

    monkeypatch.setattr(
        "yoke_core.domain.validate_webapp_pipeline_checks_remote."
        "_rest_actions_secret_names",
        unexpected_io,
    )
    counters = Counters()
    _check_github_actions_infrastructure(
        ctx, counters, "", "other-owner/other-repo",
    )

    assert counters.failed == 1
    assert "does not match verified App binding" in capsys.readouterr().out
