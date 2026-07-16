"""Tests for ``projects_environments_settings`` — environments.settings CAS.

Exercises the get/CAS-replace/merge family that
:mod:`yoke_core.domain.projects_environments_settings` owns against the
active Postgres authority, plus the parser/dispatch wiring through
``yoke_core.domain.projects`` main. The interleaved-writer cases pin the
field-note 12544/12545/12547 lost-update regression: a stale base must get
the typed conflict, never silent loss. Mirrors the fixture shape of
``test_projects_capabilities_settings.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import projects
from yoke_core.domain import projects_environments_settings as pes
from yoke_core.domain.settings_cas import SettingsConflictError
from runtime.api.fixtures.file_test_db import init_test_db


_STAGE_ID = "yoke-api-stage"
_STAGE_SETTINGS = '{"pulumi": {"activation_state": "render_only"}}'
_ACTIVE_SETTINGS = '{"pulumi": {"activation_state": "active"}}'


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _apply_environments_schema() -> None:
    """Create the ``environments`` table and seed one stage row.

    Mirrors the canonical columns (``projects_restart_schema``) minus the
    ``sites(id)`` foreign key the minimal control DB has no parent table
    for.
    """
    conn = db_backend.connect()
    try:
        conn.execute(
            """
            CREATE TABLE environments (
                id TEXT PRIMARY KEY,
                site TEXT NOT NULL,
                name TEXT NOT NULL,
                settings TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO environments (id, site, name, settings, created_at) "
            f"VALUES ('{_STAGE_ID}', 'yoke-api', 'stage', "
            f"'{_STAGE_SETTINGS}', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def env_db(tmp_path: Path) -> Iterator[str]:
    """Per-test Postgres DB with the environments table applied."""
    with init_test_db(tmp_path, apply_schema=_apply_environments_schema) as db_path:
        yield db_path


def _settings(db_path: str) -> dict:
    return json.loads(pes.cmd_environment_get_settings(_STAGE_ID, db_path=db_path))


# ---------------------------------------------------------------------------
# Handler CRUD (CAS-protected)
# ---------------------------------------------------------------------------


class TestEnvironmentSettings:
    def test_get_returns_settings_json(self, env_db: str) -> None:
        assert pes.cmd_environment_get_settings(
            _STAGE_ID, db_path=env_db
        ) == _STAGE_SETTINGS

    def test_get_set_round_trip_full_replace(self, env_db: str) -> None:
        # Full replace with the as-read text as base — the prior payload is
        # gone, not merged.
        base = pes.cmd_environment_get_settings(_STAGE_ID, db_path=env_db)
        msg = pes.cmd_environment_set_settings(
            _STAGE_ID, _ACTIVE_SETTINGS, base, db_path=env_db
        )
        assert _STAGE_ID in msg
        assert pes.cmd_environment_get_settings(
            _STAGE_ID, db_path=env_db
        ) == _ACTIVE_SETTINGS

    def test_set_without_base_is_usage_error(self, env_db: str) -> None:
        with pytest.raises(ValueError, match="--base is required"):
            pes.cmd_environment_set_settings(
                _STAGE_ID, _ACTIVE_SETTINGS, db_path=env_db
            )

    def test_get_missing_row_is_loud(self, env_db: str) -> None:
        with pytest.raises(LookupError) as exc:
            pes.cmd_environment_get_settings("yoke-api-ghost", db_path=env_db)
        assert "yoke-api-ghost" in str(exc.value)
        assert "not found" in str(exc.value)

    def test_set_missing_row_is_loud(self, env_db: str) -> None:
        with pytest.raises(LookupError, match="not found"):
            pes.cmd_environment_set_settings(
                "yoke-api-ghost", "{}", "{}", db_path=env_db
            )

    def test_set_invalid_json_is_loud(self, env_db: str) -> None:
        with pytest.raises(ValueError, match="invalid settings JSON"):
            pes.cmd_environment_set_settings(
                _STAGE_ID, "{not json", _STAGE_SETTINGS, db_path=env_db
            )

    def test_set_non_object_json_is_loud(self, env_db: str) -> None:
        with pytest.raises(ValueError, match="must be a JSON object"):
            pes.cmd_environment_set_settings(
                _STAGE_ID, "[1, 2]", _STAGE_SETTINGS, db_path=env_db
            )


# ---------------------------------------------------------------------------
# Lost-update regression: interleaved writers
# ---------------------------------------------------------------------------


class TestInterleavedWriters:
    def test_second_full_replace_on_stale_base_conflicts(
        self, env_db: str
    ) -> None:
        # A reads, B reads the same document, A writes, B writes — the
        # incident shape. B must get the typed conflict, never silent loss.
        base_a = pes.cmd_environment_get_settings(_STAGE_ID, db_path=env_db)
        base_b = pes.cmd_environment_get_settings(_STAGE_ID, db_path=env_db)
        a_doc = '{"pulumi": {"encrypted_key": "k1"}}'
        pes.cmd_environment_set_settings(
            _STAGE_ID, a_doc, base_a, db_path=env_db
        )
        with pytest.raises(SettingsConflictError, match="settings_conflict"):
            pes.cmd_environment_set_settings(
                _STAGE_ID,
                '{"hosts": {"api": "new.example"}}',
                base_b,
                db_path=env_db,
            )
        # A's write survived untouched; B's clobber never landed.
        assert pes.cmd_environment_get_settings(
            _STAGE_ID, db_path=env_db
        ) == a_doc

    def test_conflict_message_teaches_reget(self, env_db: str) -> None:
        pes.cmd_environment_set_settings(
            _STAGE_ID, _ACTIVE_SETTINGS, _STAGE_SETTINGS, db_path=env_db
        )
        with pytest.raises(SettingsConflictError) as exc:
            pes.cmd_environment_set_settings(
                _STAGE_ID, "{}", _STAGE_SETTINGS, db_path=env_db
            )
        teaching = str(exc.value)
        assert "environment-get-settings" in teaching
        assert "environment-merge-settings" in teaching


# ---------------------------------------------------------------------------
# Key-path merge (the collision-avoidance convenience)
# ---------------------------------------------------------------------------


class TestMergeSettings:
    def test_sequential_key_merges_compose(self, env_db: str) -> None:
        # The incident's two writers as merges: both land, nothing erased.
        pes.cmd_environment_merge_settings(
            _STAGE_ID, {"pulumi.stack_name": "stage-stack"}, db_path=env_db
        )
        pes.cmd_environment_merge_settings(
            _STAGE_ID, {"hosts.api": "api.stage.example"}, db_path=env_db
        )
        final = _settings(env_db)
        assert final["pulumi"]["stack_name"] == "stage-stack"
        assert final["pulumi"]["activation_state"] == "render_only"
        assert final["hosts"]["api"] == "api.stage.example"

    def test_merge_retries_once_when_base_moves(
        self, env_db: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # First read returns a stale document (a writer landed between the
        # read and the CAS write); the merge re-reads and succeeds.
        real_read = pes._read_settings_text
        calls = {"n": 0}

        def contended_read(conn, environment_id):
            calls["n"] += 1
            if calls["n"] == 1:
                return '{"pulumi": {"activation_state": "stale"}}'
            return real_read(conn, environment_id)

        monkeypatch.setattr(pes, "_read_settings_text", contended_read)
        pes.cmd_environment_merge_settings(
            _STAGE_ID, {"hosts.api": "api.stage.example"}, db_path=env_db
        )
        final = _settings(env_db)
        assert final["hosts"]["api"] == "api.stage.example"
        assert final["pulumi"]["activation_state"] == "render_only"
        assert calls["n"] >= 2

    def test_merge_conflict_after_retry_is_typed(
        self, env_db: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A writer contends on every attempt: the retry budget (one) is
        # spent and the typed conflict propagates instead of silent loss.
        monkeypatch.setattr(
            pes,
            "_read_settings_text",
            lambda conn, environment_id: '{"pulumi": {"x": "stale"}}',
        )
        with pytest.raises(SettingsConflictError, match="settings_conflict"):
            pes.cmd_environment_merge_settings(
                _STAGE_ID, {"hosts.api": "api.stage.example"}, db_path=env_db
            )

    def test_merge_missing_row_is_loud(self, env_db: str) -> None:
        with pytest.raises(LookupError, match="not found"):
            pes.cmd_environment_merge_settings(
                "yoke-api-ghost", {"a": 1}, db_path=env_db
            )

    def test_merge_refuses_non_object_intermediate(self, env_db: str) -> None:
        with pytest.raises(ValueError, match="non-object"):
            pes.cmd_environment_merge_settings(
                _STAGE_ID,
                {"pulumi.activation_state.deep": "x"},
                db_path=env_db,
            )


# ---------------------------------------------------------------------------
# CLI wiring through yoke_core.domain.projects
# ---------------------------------------------------------------------------


class TestProjectsCliWiring:
    def test_cli_get_set_round_trip(self, env_db: str, capsys) -> None:
        assert projects.main(["environment-get-settings", _STAGE_ID]) == 0
        base = capsys.readouterr().out.strip()
        assert base == _STAGE_SETTINGS

        assert projects.main(
            ["environment-set-settings", _STAGE_ID, _ACTIVE_SETTINGS,
             "--base", base]
        ) == 0
        capsys.readouterr()
        assert projects.main(["environment-get-settings", _STAGE_ID]) == 0
        assert capsys.readouterr().out.strip() == _ACTIVE_SETTINGS

    def test_cli_set_without_base_exits_2_teaching_flow(
        self, env_db: str, capsys
    ) -> None:
        rc = projects.main(
            ["environment-set-settings", _STAGE_ID, _ACTIVE_SETTINGS]
        )
        assert rc == 2
        err = capsys.readouterr().err
        assert "--base is required" in err
        assert "environment-get-settings" in err

    def test_cli_stale_base_exits_1_with_conflict(
        self, env_db: str, capsys
    ) -> None:
        assert projects.main(
            ["environment-set-settings", _STAGE_ID, _ACTIVE_SETTINGS,
             "--base", _STAGE_SETTINGS]
        ) == 0
        capsys.readouterr()
        rc = projects.main(
            ["environment-set-settings", _STAGE_ID, "{}",
             "--base", _STAGE_SETTINGS]
        )
        assert rc == 1
        assert "settings_conflict" in capsys.readouterr().err

    def test_cli_merge_sets_key_path(self, env_db: str, capsys) -> None:
        rc = projects.main(
            ["environment-merge-settings", _STAGE_ID,
             "--set", "hosts.api=api.stage.example",
             "--set", "pulumi.activation_state=active"]
        )
        assert rc == 0
        capsys.readouterr()
        final = _settings(env_db)
        assert final["hosts"]["api"] == "api.stage.example"
        assert final["pulumi"]["activation_state"] == "active"

    def test_cli_missing_row_exits_1(self, env_db: str, capsys) -> None:
        assert projects.main(["environment-get-settings", "yoke-api-ghost"]) == 1
        assert "not found" in capsys.readouterr().err

    def test_cli_invalid_json_exits_2(self, env_db: str, capsys) -> None:
        rc = projects.main(
            ["environment-set-settings", _STAGE_ID, "{bad",
             "--base", _STAGE_SETTINGS]
        )
        assert rc == 2
        assert "invalid settings JSON" in capsys.readouterr().err
