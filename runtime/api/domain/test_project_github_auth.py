"""Tests for the canonical ``project_github_auth`` resolver."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from yoke_core.domain import projects, project_github_auth as pga
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from runtime.api.fixtures.file_test_db import init_test_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _apply_schema() -> None:
    """No-op ``apply_schema`` strategy for project-github-auth tests.

    ``projects.cmd_init`` builds the project tables in each test body and uses
    schema_common for idempotent introspection, so the disposable test DB needs
    no bridge schema objects up front.
    """
    return None


@pytest.fixture
def db_path(tmp_path: Path):
    # init_test_db: a real file on SQLite, a disposable per-test database on
    # Postgres (so this module's tests do not cross-pollute the shared
    # dbname=postgres — e.g. a literal token from one test leaking into
    # test_missing_token's "no token row" assertion).
    with init_test_db(tmp_path, apply_schema=_apply_schema) as path:
        yield path


def _init_with_projects(db_path: str) -> None:
    """``cmd_init`` plus the baseline test project rows.

    Production init seeds no project rows, so the resolver fixtures seed
    the two baseline identities explicitly.
    """
    from yoke_core.domain.db_helpers import connect

    projects.cmd_init(db_path=db_path)
    conn = connect(db_path)
    try:
        seed_project_identities(conn)
    finally:
        conn.close()


def _ensure_github_capability(db_path: str) -> None:
    """CAS-write a ``(yoke, github)`` capability row, seeded or not."""
    base = projects.cmd_capability_get_settings(
        "yoke", "github", db_path=db_path
    )
    projects.cmd_capability_set_settings(
        "yoke", "github", "{}",
        base_settings_json=base, create=base is None, db_path=db_path,
    )


@pytest.fixture
def seeded_db(db_path: str) -> str:
    """DB with a ``yoke`` project that has github_repo + capability row.

    Token row is deliberately NOT seeded so individual tests control the
    secret shape.
    """
    _init_with_projects(db_path)
    projects.cmd_update(
        "yoke", "github_repo", "upyoke/yoke", db_path=db_path,
    )
    _ensure_github_capability(db_path)
    return db_path


def _set_literal(db_path: str, value: str) -> None:
    projects.cmd_capability_set_secret(
        "yoke", "github", "token", value,
        source="literal", db_path=db_path,
    )


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_resolves_literal_token(self, seeded_db: str):
        _set_literal(seeded_db, "ghp_literal_value")

        result = pga.resolve_project_github_auth(
            "yoke", db_path=seeded_db, base_env={},
        )

        assert isinstance(result, pga.ProjectGithubAuth)
        assert result.project == "yoke"
        assert result.repo == "upyoke/yoke"
        assert result.token == "ghp_literal_value"
        assert result.env["GH_TOKEN"] == "ghp_literal_value"

    def test_returns_frozen_bundle(self, seeded_db: str):
        _set_literal(seeded_db, "ghp_xyz")
        result = pga.resolve_project_github_auth(
            "yoke", db_path=seeded_db, base_env={},
        )
        with pytest.raises(Exception):
            # frozen=True forbids attribute assignment.
            result.token = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Failure modes (AC-5..AC-9, AC-11)
# ---------------------------------------------------------------------------


class TestFailureModes:
    def test_missing_capability(self, db_path: str):
        # Project row present, no github capability row: exercises the
        # ``MissingCapability`` branch.
        _init_with_projects(db_path)

        with pytest.raises(pga.MissingCapability) as info:
            pga.resolve_project_github_auth(
                "yoke", db_path=db_path, base_env={},
            )
        assert info.value.code == "missing_capability"
        assert info.value.project == "yoke"

    def test_missing_repo_metadata(self, db_path: str):
        _init_with_projects(db_path)
        # Capability present, repo blank.
        _ensure_github_capability(db_path)
        projects.cmd_update(
            "yoke", "github_repo", "", db_path=db_path,
        )

        with pytest.raises(pga.MissingRepoMetadata) as info:
            pga.resolve_project_github_auth(
                "yoke", db_path=db_path, base_env={},
            )
        assert info.value.code == "missing_repo_metadata"

    def test_missing_token(self, seeded_db: str):
        # seeded_db deliberately omits the token row.
        with pytest.raises(pga.MissingToken) as info:
            pga.resolve_project_github_auth(
                "yoke", db_path=seeded_db, base_env={},
            )
        assert info.value.code == "missing_token"

    def test_missing_token_when_literal_empty(self, seeded_db: str):
        # Row exists but value is empty whitespace → MissingToken.
        _set_literal(seeded_db, "   ")

        with pytest.raises(pga.MissingToken) as info:
            pga.resolve_project_github_auth(
                "yoke", db_path=seeded_db, base_env={},
            )
        assert info.value.code == "missing_token"

    def test_invalid_file_source(
        self, seeded_db: str, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            pga,
            "_read_github_state",
            lambda project, db_path, conn=None: (
                "yoke", True, "upyoke/yoke", "file",
            ),
        )

        with pytest.raises(pga.InvalidSecretSource) as info:
            pga.resolve_project_github_auth(
                "yoke", db_path=seeded_db, base_env={},
            )
        assert info.value.code == "invalid_secret_source"
        assert "source='file'" in str(info.value)

    def test_invalid_env_source(
        self, seeded_db: str, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.delenv("YOKE_TEST_MISSING_VAR", raising=False)
        monkeypatch.setattr(
            pga,
            "_read_github_state",
            lambda project, db_path, conn=None: (
                "yoke", True, "upyoke/yoke", "env",
            ),
        )

        with pytest.raises(pga.InvalidSecretSource) as info:
            pga.resolve_project_github_auth(
                "yoke", db_path=seeded_db, base_env={},
            )
        assert info.value.code == "invalid_secret_source"
        assert "source='env'" in str(info.value)


# ---------------------------------------------------------------------------
# Environment isolation
# ---------------------------------------------------------------------------


class TestEnvIsolation:
    def test_base_env_not_mutated(self, seeded_db: str):
        _set_literal(seeded_db, "ghp_iso")
        base = {"PATH": "/bin", "FOO": "bar"}
        base_snapshot = dict(base)

        result = pga.resolve_project_github_auth(
            "yoke", db_path=seeded_db, base_env=base,
        )

        # Returned env has GH_TOKEN; base mapping untouched.
        assert result.env["GH_TOKEN"] == "ghp_iso"
        assert "GH_TOKEN" not in base
        assert base == base_snapshot

    def test_os_environ_snapshot_when_no_base_env(
        self, seeded_db: str, monkeypatch: pytest.MonkeyPatch,
    ):
        # Resolver should capture os.environ at call time (not module
        # import time) so monkeypatch.setenv flows through.
        monkeypatch.setenv("YOKE_TEST_SENTINEL_VAR", "captured")
        _set_literal(seeded_db, "ghp_snap")

        result = pga.resolve_project_github_auth(
            "yoke", db_path=seeded_db, base_env=None,
        )
        assert result.env.get("YOKE_TEST_SENTINEL_VAR") == "captured"
        assert result.env["GH_TOKEN"] == "ghp_snap"
        # os.environ itself was not given GH_TOKEN.
        assert os.environ.get("GH_TOKEN") != "ghp_snap" or \
            "GH_TOKEN" not in os.environ


# ---------------------------------------------------------------------------
# Repair hint coverage
# ---------------------------------------------------------------------------


class TestRepairHints:
    @pytest.mark.parametrize("cls,code", [
        (pga.MissingCapability, "missing_capability"),
        (pga.MissingRepoMetadata, "missing_repo_metadata"),
        (pga.MissingToken, "missing_token"),
        (pga.InvalidSecretSource, "invalid_secret_source"),
        (pga.InvalidToken, "invalid_token"),
        (pga.TransportFailure, "transport_failure"),
    ])
    def test_hint_per_subclass(self, cls, code):
        err = cls("buzz", "test message")
        hint = pga.repair_command_hint(err, "buzz")

        assert hint  # non-empty
        # All concrete-CLI hints reference the project name except the
        # transport_failure hint, which is a generic retry instruction.
        if code != "transport_failure":
            assert "buzz" in hint

    def test_hint_class_code_attribute(self):
        # Every subclass exposes a class-level code attribute (not just
        # instance-level) so callers can branch without instantiating.
        for cls in (
            pga.MissingCapability, pga.MissingRepoMetadata,
            pga.MissingToken, pga.InvalidSecretSource,
            pga.InvalidToken, pga.TransportFailure,
        ):
            assert isinstance(cls.code, str)
            assert cls.code  # non-empty


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_surface_exports():
    """All typed diagnostics + dataclass + functions are exported."""
    expected = {
        "ProjectGithubAuthError",
        "MissingCapability",
        "MissingRepoMetadata",
        "MissingToken",
        "InvalidSecretSource",
        "InvalidToken",
        "TransportFailure",
        "ProjectGithubAuth",
        "resolve_project_github_auth",
        "repair_command_hint",
    }
    actual = set(dir(pga))
    missing = expected - actual
    assert not missing, f"missing public exports: {missing}"
