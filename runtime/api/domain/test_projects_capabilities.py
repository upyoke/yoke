"""Tests for ``projects_capabilities`` — capability listings and secrets.

Exercises the listing + secrets CRUD that
:mod:`yoke_core.domain.projects_capabilities` owns against the active
Postgres authority: the ``%s``-paramstyle upsert path, ``ON CONFLICT``
update semantics, native identity ``id`` generation when inserts omit the
column, and literal-only secret source resolution.

Pure-resolver coverage of the GitHub auth bundle lives in
``test_project_github_auth.py``; the CAS-protected settings family is
covered by ``test_projects_capabilities_settings.py``.
"""

# The shared pytest fixture intentionally shares its name with test parameters.
# ruff: noqa: F811

from __future__ import annotations

import pytest

from yoke_core.domain import projects_capabilities as pc
from yoke_core.domain import projects_capabilities_settings as pcs
from runtime.api.domain.projects_capabilities_test_helpers import cap_db as cap_db
from runtime.api.fixtures.file_test_db import connect_test_db


def _fake_secret_row(monkeypatch: pytest.MonkeyPatch, source: str):
    monkeypatch.setattr(pc, "resolve_project_id", lambda conn, project: 1)
    monkeypatch.setattr(
        pc,
        "query_one",
        lambda conn, sql, params: {"value": "external-ref", "source": source},
    )
    return object()


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------


class TestCapabilityListings:
    def test_list_returns_types_sorted(self, cap_db: str) -> None:
        pcs.cmd_capability_set_settings(
            "yoke", "ssh", "{}", create=True, db_path=cap_db
        )
        pcs.cmd_capability_set_settings(
            "yoke", "docker", "{}", create=True, db_path=cap_db
        )
        assert pc.cmd_capability_list("yoke", db_path=cap_db) == "docker\nssh"

    def test_list_settings_by_type_spans_projects_sorted(self, cap_db: str) -> None:
        # Cross-project lookups return every project's settings JSON for a
        # given type, ordered by numeric project authority.
        pcs.cmd_capability_set_settings(
            "buzz", "browser-qa", '{"enabled":"true"}', create=True, db_path=cap_db
        )
        pcs.cmd_capability_set_settings(
            "yoke", "browser-qa", '{"enabled":"false"}', create=True, db_path=cap_db
        )
        assert pc.list_capability_settings_by_type(
            "browser-qa", db_path=cap_db
        ) == ['{"enabled":"false"}', '{"enabled":"true"}']


# ---------------------------------------------------------------------------
# Native identity (inserts omit id)
# ---------------------------------------------------------------------------


class TestIdentityGeneration:
    def test_settings_insert_omitting_id_autogenerates_distinct_ids(
        self, cap_db: str
    ) -> None:
        # The write path inserts (project, type, settings, created_at) with no
        # id column; Postgres identity fills it. Distinct rows get distinct ids.
        pcs.cmd_capability_set_settings(
            "yoke", "ssh", "{}", create=True, db_path=cap_db
        )
        pcs.cmd_capability_set_settings(
            "buzz", "ssh", "{}", create=True, db_path=cap_db
        )
        conn = connect_test_db(cap_db)
        try:
            ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM project_capabilities ORDER BY id"
                ).fetchall()
            ]
        finally:
            conn.close()
        assert len(ids) == 2
        assert all(isinstance(i, int) for i in ids)
        assert ids[0] != ids[1]


# ---------------------------------------------------------------------------
# Secrets CRUD + source resolution
# ---------------------------------------------------------------------------


class TestCapabilitySecrets:
    def test_set_then_get_literal(self, cap_db: str) -> None:
        pc.cmd_capability_set_secret(
            "yoke", "deploy", "token", "deploy_secret", db_path=cap_db
        )
        assert pc.cmd_capability_get_secret(
            "yoke", "deploy", "token", db_path=cap_db
        ) == "deploy_secret"

    def test_get_missing_returns_none(self, cap_db: str) -> None:
        assert pc.cmd_capability_get_secret(
            "yoke", "deploy", "absent", db_path=cap_db
        ) is None

    def test_get_secret_rejects_file_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = _fake_secret_row(monkeypatch, "file")
        with pytest.raises(ValueError, match="unsupported source='file'"):
            pc.cmd_capability_get_secret(
                "yoke", "deploy", "token", conn=conn
            )

    def test_get_secret_rejects_env_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOKE_TEST_CAP_SECRET", "env_token")
        conn = _fake_secret_row(monkeypatch, "env")
        with pytest.raises(ValueError, match="unsupported source='env'"):
            pc.cmd_capability_get_secret(
                "yoke", "deploy", "token", conn=conn
            )

    def test_get_secret_rejects_missing_file_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = _fake_secret_row(monkeypatch, "file")
        with pytest.raises(ValueError, match="unsupported source='file'"):
            pc.cmd_capability_get_secret(
                "yoke", "deploy", "token", conn=conn
            )

    def test_set_secret_invalid_source_raises(self, cap_db: str) -> None:
        with pytest.raises(ValueError, match="source='literal'"):
            pc.cmd_capability_set_secret(
                "yoke", "deploy", "token", "x",
                source="file", db_path=cap_db,
            )

    def test_set_secret_upsert_updates_in_place(self, cap_db: str) -> None:
        # ON CONFLICT(project, type, key) DO UPDATE — single row, new value.
        pc.cmd_capability_set_secret(
            "yoke", "deploy", "token", "old", db_path=cap_db
        )
        pc.cmd_capability_set_secret(
            "yoke", "deploy", "token", "new", db_path=cap_db
        )
        assert pc.cmd_capability_get_secret(
            "yoke", "deploy", "token", db_path=cap_db
        ) == "new"
        assert pc.cmd_capability_list_secrets(
            "yoke", "deploy", db_path=cap_db
        ) == "token"

    def test_get_secret_uses_supplied_connection_left_open(
        self, cap_db: str
    ) -> None:
        # When ``conn`` is supplied the read runs on the caller's connection and
        # the helper leaves it open (own_conn=False).
        pc.cmd_capability_set_secret(
            "yoke", "deploy", "token", "shared", db_path=cap_db
        )
        conn = connect_test_db(cap_db)
        try:
            assert pc.cmd_capability_get_secret(
                "yoke", "deploy", "token", conn=conn
            ) == "shared"
            # Still usable — the helper did not close the borrowed connection.
            assert conn.execute("SELECT 1").fetchone()[0] == 1
        finally:
            conn.close()
