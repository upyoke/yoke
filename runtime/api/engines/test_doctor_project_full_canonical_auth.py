"""Doctor HC tests for the canonical project-GitHub-auth resolver path.

Covers ``HC-project-gh-token``, which goes through
``yoke_core.domain.project_github_auth.resolve_project_github_auth``.

The older project-HC fixtures plus the rest of the project-HC suite live in
``test_doctor_project_full.py``.  The
two files share a tiny on-disk DB fixture; rather than reach back into
the sibling, we open our own seeded DB through ``projects.cmd_init``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_project_gh_token,
)
from runtime.api.fixtures.file_test_db import init_test_db


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """Backend-aware DB token seeded via ``projects.cmd_init``.

    The canonical resolver opens its own connection from ``args.db_path``,
    so fixtures must persist through a path token — not just an in-memory conn.
    """
    from yoke_core.domain import projects as p
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_seed_test_helpers import (
        seed_project_identities,
    )

    def _apply() -> None:
        p.cmd_init()
        conn = connect()
        try:
            seed_project_identities(conn)
        finally:
            conn.close()
        p.cmd_capability_set_settings(
            "buzz", "github",
            '{"repo_owner":"example-org","repo_name":"buzz"}',
            base_settings_json=None, create=True,
        )

    with init_test_db(tmp_path, apply_schema=_apply) as path:
        yield path


def _seed_buzz_token(db_path: str, value: str = "ghp_buzz_secret") -> None:
    from yoke_core.domain import projects as p
    p.cmd_capability_set_secret(
        "buzz", "github", "token", value,
        source="literal", db_path=db_path,
    )


def _args(**overrides) -> DoctorArgs:
    defaults = dict(
        file=None, fix=False, only=None, quick=False,
        project="buzz", db_path=None,
    )
    defaults.update(overrides)
    return DoctorArgs(**defaults)


def _run_hc(fn, conn, **kwargs) -> RecordCollector:
    rec = RecordCollector()
    fn(conn, _args(**kwargs), rec)
    return rec


def _patch_invalid_source(monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    from yoke_core.domain import project_github_auth as pga
    import yoke_core.engines.doctor_hc_worktrees_gh_project as hc

    def _raise_invalid(project, *, db_path=None, conn=None, base_env=None):
        raise pga.InvalidSecretSource(
            project,
            f"project '{project}' github token uses unsupported "
            f"capability_secrets.source={source!r}",
        )

    monkeypatch.setattr(hc, "resolve_project_github_auth", _raise_invalid)


class TestProjectGhTokenCanonical:
    """Doctor now resolves project GitHub auth through the canonical
    resolver (``project_github_auth.resolve_project_github_auth``).
    Fixtures seed ``capability_secrets`` with Yoke-owned literal values.
    """

    def test_passes_with_literal_secret(self, db_path: str):
        from yoke_core.domain.db_helpers import connect
        _seed_buzz_token(db_path)
        conn = connect(db_path)
        try:
            rec = _run_hc(
                hc_project_gh_token, conn,
                project="buzz", db_path=db_path,
            )
        finally:
            conn.close()
        assert rec.results[0].result == "PASS"
        assert "capability_secrets" in rec.results[0].detail

    def test_fails_with_file_source(
        self, db_path: str, monkeypatch: pytest.MonkeyPatch
    ):
        from yoke_core.domain.db_helpers import connect
        _patch_invalid_source(monkeypatch, "file")
        conn = connect(db_path)
        try:
            rec = _run_hc(
                hc_project_gh_token, conn,
                project="buzz", db_path=db_path,
            )
        finally:
            conn.close()
        assert rec.results[0].result == "FAIL"
        assert "capability_secrets.source='file'" in rec.results[0].detail
        assert "capability secret set" in rec.results[0].detail

    def test_fails_with_env_source(self, db_path: str, monkeypatch):
        from yoke_core.domain.db_helpers import connect
        _patch_invalid_source(monkeypatch, "env")
        conn = connect(db_path)
        try:
            rec = _run_hc(
                hc_project_gh_token, conn,
                project="buzz", db_path=db_path,
            )
        finally:
            conn.close()
        assert rec.results[0].result == "FAIL"
        assert "capability_secrets.source='env'" in rec.results[0].detail
        assert "capability secret set" in rec.results[0].detail

    def test_fails_with_repair_hint_when_no_token(self, db_path: str):
        from yoke_core.domain.db_helpers import connect
        # No capability_secrets row at all → MissingToken → FAIL + hint.
        conn = connect(db_path)
        try:
            rec = _run_hc(
                hc_project_gh_token, conn,
                project="buzz", db_path=db_path,
            )
        finally:
            conn.close()
        assert rec.results[0].result == "FAIL"
        assert "Repair:" in rec.results[0].detail
        assert "capability secret set" in rec.results[0].detail

    def test_fails_when_capability_missing(self, db_path: str):
        from yoke_core.domain.db_helpers import connect
        conn = connect(db_path)
        try:
            conn.execute(
                "DELETE FROM project_capabilities "
                "WHERE project_id=(SELECT id FROM projects WHERE slug='buzz') "
                "AND type='github'"
            )
            conn.commit()
            rec = _run_hc(
                hc_project_gh_token, conn,
                project="buzz", db_path=db_path,
            )
        finally:
            conn.close()
        assert rec.results[0].result == "FAIL"
        assert (
            "missing_capability" in rec.results[0].detail
            or "capability-add" in rec.results[0].detail
        )

    def test_no_global_auth_fallback_string(self, db_path: str):
        """The obsolete global-auth WARN string is gone."""
        from yoke_core.domain.db_helpers import connect
        conn = connect(db_path)
        try:
            rec = _run_hc(
                hc_project_gh_token, conn,
                project="buzz", db_path=db_path,
            )
        finally:
            conn.close()
        retired_warning = "Using " + "global auth"
        assert retired_warning not in rec.results[0].detail
