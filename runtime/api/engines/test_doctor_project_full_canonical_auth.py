"""Doctor HC tests for the canonical project-GitHub-auth resolver path.

Covers ``HC-project-gh-auth``, which goes through
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
    hc_project_gh_auth,
)
from runtime.api.fixtures.file_test_db import init_test_db
from yoke_core.domain.project_github_auth import ProjectGithubAuth


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


def _patch_resolved_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    import yoke_core.engines.doctor_hc_worktrees_gh_project as hc

    def _resolve(project, *, db_path=None, conn=None, base_env=None):
        return ProjectGithubAuth(
            project=project,
            repo="example-org/buzz",
            token="ghs_installation_token",
            env={"GH_TOKEN": "ghs_installation_token"},
            installation_id="12345",
            token_source="github_app_installation",
        )

    monkeypatch.setattr(hc, "resolve_project_github_auth", _resolve)


class TestProjectGhAuthCanonical:
    """Doctor now resolves project GitHub auth through the canonical
    resolver (``project_github_auth.resolve_project_github_auth``).
    """

    def test_passes_with_resolved_app_auth(
        self, db_path: str, monkeypatch: pytest.MonkeyPatch,
    ):
        from yoke_core.domain.db_helpers import connect
        _patch_resolved_auth(monkeypatch)
        conn = connect(db_path)
        try:
            rec = _run_hc(
                hc_project_gh_auth, conn,
                project="buzz", db_path=db_path,
            )
        finally:
            conn.close()
        assert rec.results[0].result == "PASS"
        assert "GitHub App auth" in rec.results[0].check_name
        assert "project repo binding" in rec.results[0].detail

    def test_fails_with_repair_hint_when_binding_missing(self, db_path: str):
        from yoke_core.domain.db_helpers import connect
        conn = connect(db_path)
        try:
            rec = _run_hc(
                hc_project_gh_auth, conn,
                project="buzz", db_path=db_path,
            )
        finally:
            conn.close()
        assert rec.results[0].result == "FAIL"
        assert "Repair:" in rec.results[0].detail
        assert "projects github-binding bind" in rec.results[0].detail

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
                hc_project_gh_auth, conn,
                project="buzz", db_path=db_path,
            )
        finally:
            conn.close()
        assert rec.results[0].result == "FAIL"
        assert "GitHub App capability row" in rec.results[0].detail
        assert "projects github-binding bind" in rec.results[0].detail

    def test_no_global_auth_fallback_string(self, db_path: str):
        """The obsolete global-auth WARN string is gone."""
        from yoke_core.domain.db_helpers import connect
        conn = connect(db_path)
        try:
            rec = _run_hc(
                hc_project_gh_auth, conn,
                project="buzz", db_path=db_path,
            )
        finally:
            conn.close()
        retired_warning = "Using " + "global auth"
        assert retired_warning not in rec.results[0].detail
