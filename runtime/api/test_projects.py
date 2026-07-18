"""Pytest suite for ``yoke_core.domain.projects``: CRUD and capability config.

Init/seed-data tests, secret handling, deploy-env resolution, the CLI entry
point, and the project-structure coexistence assertions live in sibling files
(``test_projects_init.py``, ``test_projects_secrets.py``,
``test_projects_cli.py``, ``test_projects_structure.py``).

Each test runs against a backend-appropriate disposable DB via
:func:`init_test_db`: a per-test SQLite file on SQLite, a per-test Postgres
database on Postgres. The previous "create a temp file + ``cmd_init`` against
it" pattern shared one database on Postgres (``cmd_init``'s ``db_path`` is
ignored when the backend factory targets the DSN), so seed rows and capability
upserts leaked across tests. ``projects.cmd_init`` now routes catalog probes
through backend-aware schema helpers, so no Postgres introspection shims are
needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

from yoke_core.domain import projects
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_seed_test_helpers import (
    seed_project_identities,
)
from runtime.api.fixtures.file_test_db import init_test_db


# ---------------------------------------------------------------------------
# init_test_db apply_schema strategies
# ---------------------------------------------------------------------------
def _apply_projects_schema() -> None:
    """Strategy seeding the full project schema."""
    projects.cmd_init()
    conn = connect()
    try:
        seed_project_identities(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def initialized_db(tmp_path: Path) -> Iterator[str]:
    """Disposable DB token after running ``cmd_init`` (tables + seed exist)."""
    with init_test_db(tmp_path, apply_schema=_apply_projects_schema) as path:
        yield path


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_create_and_get(self, initialized_db: str):
        msg = projects.cmd_create("acme", "Acme Corp", db_path=initialized_db)
        assert "acme" in msg.lower()

        result = projects.cmd_get("acme", db_path=initialized_db)
        assert result is not None
        assert "acme" in result.lower()

    def test_create_duplicate_raises(self, initialized_db: str):
        projects.cmd_create("dup", "Dup", db_path=initialized_db)
        with pytest.raises(Exception):
            projects.cmd_create("dup", "Dup Again", db_path=initialized_db)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

class TestGet:
    def test_get_full_row_pipe_delimited(self, initialized_db: str):
        result = projects.cmd_get("yoke", db_path=initialized_db)
        assert result is not None
        assert "|" in result
        fields = result.split("|")
        # Numeric id is authority; slug remains the human/operator identifier.
        assert fields[0] == "1"
        assert fields[1] == "yoke"

    def test_get_single_field(self, initialized_db: str):
        name = projects.cmd_get("yoke", field="name", db_path=initialized_db)
        assert name == "Yoke"

    def test_get_nonexistent_returns_none(self, initialized_db: str):
        result = projects.cmd_get("nonexistent", db_path=initialized_db)
        assert result is None

    def test_get_nonexistent_field_returns_none(self, initialized_db: str):
        result = projects.cmd_get("nonexistent", field="name", db_path=initialized_db)
        assert result is None

    def test_get_invalid_field_raises(self, initialized_db: str):
        with pytest.raises(ValueError, match="unknown field"):
            projects.cmd_get("yoke", field="bogus_field", db_path=initialized_db)

    def test_get_invalid_field_with_hint(self, initialized_db: str):
        with pytest.raises(ValueError, match="Hint"):
            projects.cmd_get("yoke", field="capabilities", db_path=initialized_db)

    def test_get_empty_field_returns_empty_string(self, initialized_db: str):
        # ``cmd_get`` returns "" for NULL columns.  Use a freshly-created
        # project whose github_repo was never set.
        projects.cmd_create(
            "blank", "Blank", db_path=initialized_db,
        )
        result = projects.cmd_get(
            "blank", field="github_repo", db_path=initialized_db,
        )
        assert result == ""

    def test_yoke_has_github_repo_after_init(self, initialized_db: str):
        result = projects.cmd_get(
            "yoke", field="github_repo", db_path=initialized_db,
        )
        assert result == "upyoke/yoke"

    def test_init_seeds_no_capability_rows(self, initialized_db: str):
        """Per-project capabilities are onboarding data, never init seeds."""
        assert projects.cmd_has_capability(
            "yoke", "github", db_path=initialized_db,
        ) is False
        settings = projects.cmd_capability_get_settings(
            "yoke", "github", db_path=initialized_db,
        )
        assert settings is None


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

class TestList:
    def test_list_returns_all(self, initialized_db: str):
        output = projects.cmd_list(db_path=initialized_db)
        lines = output.strip().split("\n")
        slugs = [line.split("|")[1] for line in lines]
        assert "externalwebapp" in slugs
        assert "yoke" in slugs

    def test_list_includes_created_project(self, initialized_db: str):
        projects.cmd_create("zeta", "Zeta", db_path=initialized_db)
        output = projects.cmd_list(db_path=initialized_db)
        slugs = [line.split("|")[1] for line in output.strip().split("\n")]
        assert "zeta" in slugs


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

class TestUpdate:
    def test_update_field(self, initialized_db: str):
        projects.cmd_update("yoke", "github_repo", "owner/yoke", db_path=initialized_db)
        val = projects.cmd_get("yoke", field="github_repo", db_path=initialized_db)
        assert val == "owner/yoke"

    def test_update_invalid_field_raises(self, initialized_db: str):
        with pytest.raises(ValueError, match="unknown field"):
            projects.cmd_update("yoke", "bogus", "val", db_path=initialized_db)

    def test_update_id_raises(self, initialized_db: str):
        with pytest.raises(ValueError, match="cannot update primary key"):
            projects.cmd_update("yoke", "id", "new-id", db_path=initialized_db)

    def test_update_nonexistent_project_raises(self, initialized_db: str):
        with pytest.raises(LookupError, match="not found"):
            projects.cmd_update("ghost", "name", "Ghost", db_path=initialized_db)


# ---------------------------------------------------------------------------
# has-capability
# ---------------------------------------------------------------------------

class TestHasCapability:
    def test_present_returns_true(self, initialized_db: str):
        projects.cmd_capability_set_settings(
            "externalwebapp", "deploy", "{}",
            base_settings_json=None, create=True, db_path=initialized_db,
        )
        assert projects.cmd_has_capability("externalwebapp", "deploy", db_path=initialized_db) is True

    def test_absent_returns_false(self, initialized_db: str):
        assert projects.cmd_has_capability("yoke", "nonexistent-cap", db_path=initialized_db) is False

    def test_absent_project_returns_false(self, initialized_db: str):
        assert projects.cmd_has_capability("no-such-project", "github", db_path=initialized_db) is False


# ---------------------------------------------------------------------------
# capability-get-settings / capability-set-settings
# ---------------------------------------------------------------------------

class TestCapabilitySettings:
    def test_create_and_get_settings(self, initialized_db: str):
        settings = json.dumps({"user": "deploy", "host": "prod.example.com"})
        projects.cmd_capability_set_settings(
            "yoke", "ssh", settings, create=True, db_path=initialized_db
        )

        result = projects.cmd_capability_get_settings("yoke", "ssh", db_path=initialized_db)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["user"] == "deploy"

    def test_get_settings_nonexistent_capability(self, initialized_db: str):
        result = projects.cmd_capability_get_settings("yoke", "nonexistent", db_path=initialized_db)
        assert result is None

    def test_merge_settings_creates_missing_capability(self, initialized_db: str):
        projects.cmd_capability_merge_settings(
            "yoke", "nonexistent", {"enabled": True}, db_path=initialized_db
        )
        result = projects.cmd_capability_get_settings(
            "yoke", "nonexistent", db_path=initialized_db
        )
        assert json.loads(result or "{}") == {"enabled": True}

    def test_capability_list(self, initialized_db: str):
        # Merge works whether or not the seed already created the row
        # (cmd_init seeds a yoke docker capability).
        projects.cmd_capability_merge_settings(
            "yoke", "ssh", {"present": True}, db_path=initialized_db
        )
        projects.cmd_capability_merge_settings(
            "yoke", "docker", {"present": True}, db_path=initialized_db
        )

        output = projects.cmd_capability_list("yoke", db_path=initialized_db)
        types = output.strip().split("\n")
        assert "ssh" in types
        assert "docker" in types
