"""Tests for the path-claim integration-target validator.

Covers AC-7 (omitted target defaults to project trunk), AC-8 (supplied
unresolved target fails before claim mutation), and AC-9 (omitted-flag
defaulting + supplied valid acceptance + blank/missing
``projects.default_branch`` fallback).
"""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path

import pytest

from yoke_core.domain.path_claims_register_validate_integration_target import (
    IntegrationTargetUnresolvable,
    resolve_and_validate_integration_target,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import (
    clear_machine_checkout,
    register_machine_checkout,
)

_PROJECTS_DDL = (
    "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, "
    "name TEXT DEFAULT '', default_branch TEXT DEFAULT 'main', "
    "public_item_prefix TEXT DEFAULT 'YOK')"
)
_ITEMS_DDL = "CREATE TABLE items (id INTEGER PRIMARY KEY, project_id INTEGER)"
_PROJECT_IDS = {"alpha": 10, "beta": 11}


@contextlib.contextmanager
def _validator_db(tmp_path, *, projects: bool = True, items: bool = True):
    """Disposable Postgres DB with the validator's minimal projects/items schema.

    The validator reads ``items.project_id`` and ``projects.default_branch``;
    checkout location comes from machine config. The skip-on-missing-table
    paths are exercised by omitting one or both tables; each read fails soft
    to the skip default on the active backend.
    """
    from yoke_core.domain import db_backend

    def _apply() -> None:
        c = db_backend.connect()
        try:
            if projects:
                c.execute(_PROJECTS_DDL)
            if items:
                c.execute(_ITEMS_DDL)
            c.commit()
        finally:
            c.close()

    with init_test_db(tmp_path, apply_schema=_apply) as db_path:
        c = connect_test_db(db_path)
        try:
            yield c
        finally:
            c.close()


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True, capture_output=True, text=True,
    ).stdout


def _init_repo_with_main(repo_root: Path) -> Path:
    repo_root.mkdir(parents=True, exist_ok=True)
    _git(repo_root, "init", "-q", "-b", "main")
    _git(repo_root, "config", "user.email", "test@example.test")
    _git(repo_root, "config", "user.name", "test")
    (repo_root / "README.md").write_text("seed\n")
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-q", "-m", "seed")
    return repo_root


@pytest.fixture
def conn(tmp_path):
    with _validator_db(tmp_path) as c:
        yield c


def _seed(conn, item_id: int, project: str, repo_path: str | None = None,
          default_branch: str | None = "main") -> None:
    project_id = int(project) if str(project).isdigit() else _PROJECT_IDS.setdefault(project, len(_PROJECT_IDS) + 10)
    if repo_path:
        checkout = Path(repo_path)
        register_machine_checkout(checkout.parent, checkout, project_id)
    else:
        clear_machine_checkout(project_id)
    conn.execute(
        "INSERT INTO projects (id, slug, name, default_branch) "
        "VALUES (%s, %s, %s, %s)",
        (project_id, project, project.title(), default_branch),
    )
    conn.execute(
        "INSERT INTO items (id, project_id) VALUES (%s, %s)",
        (item_id, project_id),
    )


def test_supplied_valid_target_accepted(tmp_path, conn):
    repo = _init_repo_with_main(tmp_path / "alpha")
    _seed(conn, 1, "alpha", str(repo), "main")
    result = resolve_and_validate_integration_target(
        conn, item_id=1, supplied_target="main",
    )
    assert result == "main"


def test_supplied_unresolved_target_rejected(tmp_path, conn):
    repo = _init_repo_with_main(tmp_path / "alpha")
    _seed(conn, 1, "alpha", str(repo), "main")
    with pytest.raises(IntegrationTargetUnresolvable) as exc_info:
        resolve_and_validate_integration_target(
            conn, item_id=1, supplied_target="YOK-9999",
        )
    msg = str(exc_info.value)
    assert "YOK-9999" in msg
    assert "10" in msg
    assert "main" in msg


def test_omitted_target_defaults_to_project_trunk(tmp_path, conn):
    repo = _init_repo_with_main(tmp_path / "alpha")
    _seed(conn, 1, "alpha", str(repo), "main")
    result = resolve_and_validate_integration_target(
        conn, item_id=1, supplied_target=None,
    )
    assert result == "main"


def test_omitted_target_uses_configured_default_branch(tmp_path, conn):
    repo_root = tmp_path / "alpha"
    repo_root.mkdir()
    _git(repo_root, "init", "-q", "-b", "trunk")
    _git(repo_root, "config", "user.email", "test@example.test")
    _git(repo_root, "config", "user.name", "test")
    (repo_root / "README.md").write_text("seed\n")
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-q", "-m", "seed")
    _seed(conn, 1, "alpha", str(repo_root), "trunk")
    result = resolve_and_validate_integration_target(
        conn, item_id=1, supplied_target=None,
    )
    assert result == "trunk"


def test_omitted_target_falls_back_to_main_when_default_branch_null(
    tmp_path, conn,
):
    repo = _init_repo_with_main(tmp_path / "alpha")
    _seed(conn, 1, "alpha", str(repo), None)
    result = resolve_and_validate_integration_target(
        conn, item_id=1, supplied_target=None,
    )
    assert result == "main"


def test_omitted_target_falls_back_to_main_when_default_branch_blank(
    tmp_path, conn,
):
    repo = _init_repo_with_main(tmp_path / "alpha")
    _seed(conn, 1, "alpha", str(repo), "   ")
    result = resolve_and_validate_integration_target(
        conn, item_id=1, supplied_target=None,
    )
    assert result == "main"


def test_validation_skips_when_checkout_missing(conn):
    _seed(conn, 1, "alpha", None, "main")
    result = resolve_and_validate_integration_target(
        conn, item_id=1, supplied_target="YOK-anything",
    )
    assert result == "YOK-anything"


def test_validation_skips_when_repo_path_not_a_git_repo(tmp_path, conn):
    not_a_repo = tmp_path / "alpha"
    not_a_repo.mkdir()
    _seed(conn, 1, "alpha", str(not_a_repo), "main")
    result = resolve_and_validate_integration_target(
        conn, item_id=1, supplied_target="YOK-anything",
    )
    assert result == "YOK-anything"


def test_validation_skips_when_item_has_no_project(tmp_path, conn):
    conn.execute("INSERT INTO items (id, project_id) VALUES (1, NULL)")
    result = resolve_and_validate_integration_target(
        conn, item_id=1, supplied_target="any",
    )
    assert result == "any"


def test_omitted_target_with_no_project_falls_back_to_main(conn):
    conn.execute("INSERT INTO items (id, project_id) VALUES (1, NULL)")
    result = resolve_and_validate_integration_target(
        conn, item_id=1, supplied_target=None,
    )
    assert result == "main"


def test_validation_skips_when_projects_table_missing(tmp_path):
    with _validator_db(tmp_path, projects=False) as c:
        c.execute("INSERT INTO items (id, project_id) VALUES (1, 10)")
        result = resolve_and_validate_integration_target(
            c, item_id=1, supplied_target="anything",
        )
        assert result == "anything"


def test_validation_skips_when_items_table_missing(tmp_path):
    with _validator_db(tmp_path, projects=False, items=False) as c:
        result = resolve_and_validate_integration_target(
            c, item_id=1, supplied_target="anything",
        )
        assert result == "anything"


def test_error_message_recommends_configured_trunk(tmp_path, conn):
    repo_root = tmp_path / "alpha"
    repo_root.mkdir()
    _git(repo_root, "init", "-q", "-b", "develop")
    _git(repo_root, "config", "user.email", "test@example.test")
    _git(repo_root, "config", "user.name", "test")
    (repo_root / "README.md").write_text("seed\n")
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-q", "-m", "seed")
    _seed(conn, 1, "alpha", str(repo_root), "develop")
    with pytest.raises(IntegrationTargetUnresolvable) as exc_info:
        resolve_and_validate_integration_target(
            conn, item_id=1, supplied_target="missing-branch",
        )
    msg = str(exc_info.value)
    assert "develop" in msg
    assert "missing-branch" in msg
