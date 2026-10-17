"""Universe levels storage, the project override, and their registered reads."""

from __future__ import annotations

import json
import sqlite3

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.levels import (
    LevelsError,
    default_levels,
    levels_payload,
    parse_levels,
)
from yoke_contracts.model_reference_data import MODEL_RECORDS
from yoke_core.domain import universe_levels
from yoke_core.domain.handlers import projects_level_summary
from yoke_core.domain.handlers.universe_levels import (
    handle_universe_levels_get,
    handle_universe_levels_reset,
    handle_universe_levels_set,
)

CUSTOM = [
    {
        "name": "ONLY",
        "glyph": "\U0001f680",
        "options": [
            {
                "model": "gpt-6.1-sol",
                "min_effort": "high",
            }
        ],
    }
]
OTHER = [{**CUSTOM[0], "name": "OTHER"}]
PROJECT_ID = 7


class _Conn:
    """An sqlite connection the handlers may open and close per call."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *_exc):
        return False


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE universe_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, updated_by_actor_id INTEGER)"
    )
    connection.execute(
        "CREATE TABLE project_capabilities "
        "(id INTEGER PRIMARY KEY, project_id INTEGER, type TEXT, settings TEXT)"
    )
    return connection


@pytest.fixture
def handlers(conn, monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect", lambda *_a, **_k: _Conn(conn)
    )
    monkeypatch.setattr(
        "yoke_core.domain.project_identity.resolve_project_id",
        lambda *_a, **_k: PROJECT_ID,
    )
    monkeypatch.setattr(
        projects_level_summary, "_authorized_project_ref", lambda *_a: str(PROJECT_ID)
    )
    monkeypatch.setattr(
        "yoke_core.domain.model_reference_store.revision_at",
        lambda *_a, **_k: {"records": MODEL_RECORDS},
    )
    return conn


def _override(conn, settings) -> None:
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) VALUES (?, ?, ?)",
        (PROJECT_ID, "session-routing", json.dumps(settings)),
    )


def _call(handler, function_id, payload, actor_id="3"):
    return handler(
        FunctionCallRequest(
            function=function_id,
            actor=ActorContext(actor_id=actor_id, session_id="levels-test"),
            target=TargetRef(kind="global"),
            payload=payload,
        )
    )


class TestStore:
    def test_an_empty_universe_reads_the_shipped_scheme(self, conn):
        assert universe_levels.stored_universe_levels(conn) is None
        assert universe_levels.effective_levels(conn, None) == (
            default_levels(),
            "default",
        )

    def test_a_write_is_validated_stored_and_replaced(self, conn):
        universe_levels.write_universe_levels(conn, CUSTOM, actor_id=3)
        assert universe_levels.stored_universe_levels(conn) == CUSTOM
        replacement = json.loads(json.dumps(CUSTOM))
        replacement[0]["glyph"] = "\U0001f52c"
        universe_levels.write_universe_levels(conn, replacement, actor_id=4)
        assert universe_levels.stored_universe_levels(conn) == replacement
        rows = conn.execute("SELECT key, updated_by_actor_id FROM universe_settings")
        assert rows.fetchall() == [("levels", 4)]

    def test_writing_the_shipped_defaults_stores_nothing(self, conn):
        universe_levels.write_universe_levels(conn, CUSTOM, actor_id=3)
        levels, source = universe_levels.write_universe_levels(
            conn, levels_payload(default_levels()), actor_id=4
        )
        assert (levels, source) == (default_levels(), "default")
        assert universe_levels.stored_universe_levels(conn) is None
        assert universe_levels.effective_levels(conn, None)[1] == "default"

    def test_clear_returns_the_universe_to_shipped_defaults(self, conn):
        assert universe_levels.clear_universe_levels(conn) is False
        universe_levels.write_universe_levels(conn, CUSTOM, actor_id=3)
        assert universe_levels.clear_universe_levels(conn) is True
        assert universe_levels.effective_levels(conn, None)[1] == "default"

    def test_shipped_defaults_differ_tracks_the_stored_document(
        self, conn, monkeypatch
    ):
        assert universe_levels.shipped_defaults_differ(conn) is None
        universe_levels.write_universe_levels(conn, CUSTOM, actor_id=3)
        assert universe_levels.shipped_defaults_differ(conn) is True
        monkeypatch.setattr(
            universe_levels, "default_levels", lambda: parse_levels(CUSTOM)
        )
        assert universe_levels.shipped_defaults_differ(conn) is False

    def test_an_invalid_write_stores_nothing(self, conn):
        with pytest.raises(LevelsError):
            universe_levels.write_universe_levels(conn, [{"name": "x"}], actor_id=3)
        assert universe_levels.stored_universe_levels(conn) is None

    def test_a_project_override_wins_over_the_universe(self, conn):
        universe_levels.write_universe_levels(conn, CUSTOM, actor_id=3)
        _override(conn, {"levels": OTHER})
        levels, source = universe_levels.effective_levels(conn, PROJECT_ID)
        assert (source, levels[0].name) == ("project", "OTHER")
        assert universe_levels.effective_levels(conn, PROJECT_ID + 1)[1] == "universe"

    def test_an_unreadable_stored_document_names_its_repair(self, conn):
        conn.execute(
            "INSERT INTO universe_settings VALUES ('levels', 'not json', 'now', NULL)"
        )
        with pytest.raises(universe_levels.UniverseLevelsError) as caught:
            universe_levels.effective_levels(conn, None)
        assert caught.value.code == "levels_document_unreadable"
        assert "yoke settings set levels" in str(caught.value)


class TestUniverseHandlers:
    def test_get_reports_the_shipped_default(self, handlers):
        outcome = _call(handle_universe_levels_get, "universe.levels.get", {})
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["source"] == "default"
        assert [level["name"] for level in outcome.result_payload["levels"]] == [
            "INTERN",
            "JUNIOR",
            "SENIOR",
            "PRINCIPAL",
        ]

    def test_set_stores_and_get_reads_it_back(self, handlers):
        outcome = _call(
            handle_universe_levels_set, "universe.levels.set", {"levels": CUSTOM}
        )
        assert outcome.primary_success, outcome.error
        read = _call(handle_universe_levels_get, "universe.levels.get", {})
        assert read.result_payload == {
            "source": "universe",
            "levels": CUSTOM,
            "shipped_defaults_differ": True,
        }

    def test_reset_returns_get_to_the_shipped_default(self, handlers):
        _call(handle_universe_levels_set, "universe.levels.set", {"levels": CUSTOM})
        reset = _call(handle_universe_levels_reset, "universe.levels.reset", {})
        assert reset.primary_success, reset.error
        assert reset.result_payload["cleared"] is True
        read = _call(handle_universe_levels_get, "universe.levels.get", {})
        assert read.result_payload["source"] == "default"
        assert "shipped_defaults_differ" not in read.result_payload
        again = _call(handle_universe_levels_reset, "universe.levels.reset", {})
        assert again.result_payload["cleared"] is False

    def test_set_with_the_shipped_defaults_leaves_no_row(self, handlers):
        outcome = _call(
            handle_universe_levels_set,
            "universe.levels.set",
            {"levels": levels_payload(default_levels())},
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["source"] == "default"
        read = _call(handle_universe_levels_get, "universe.levels.get", {})
        assert read.result_payload["source"] == "default"

    def test_set_refuses_by_name_and_points_at_the_field(self, handlers):
        bad = json.loads(json.dumps(CUSTOM))
        bad[0]["options"][0]["min_effort"] = "extreme"
        outcome = _call(
            handle_universe_levels_set, "universe.levels.set", {"levels": bad}
        )
        assert not outcome.primary_success
        assert outcome.error.code == "level_min_effort_invalid"
        assert outcome.error.jsonpath == "$.payload.levels[0].options[0].min_effort"


class TestLevelSummary:
    def _summary(self):
        return _call(
            projects_level_summary.handle_level_summary_get,
            "projects.level_summary.get",
            {"project": "yoke"},
        )

    def test_a_project_without_override_reads_the_universe(self, handlers):
        outcome = self._summary()
        assert outcome.primary_success, outcome.error
        payload = outcome.result_payload
        assert (payload["source"], payload["configured"]) == ("default", False)
        assert payload["levels"] == levels_payload(default_levels())

    def test_a_project_override_is_reported_as_configured(self, handlers):
        _override(handlers, {"levels": CUSTOM})
        payload = self._summary().result_payload
        assert (payload["source"], payload["configured"]) == ("project", True)
        assert payload["levels"] == CUSTOM

    def test_a_stored_document_that_no_longer_validates_names_the_repair(
        self, handlers
    ):
        _override(handlers, {"levels": [{"name": "ONLY", "glyph": "x", "options": []}]})
        outcome = self._summary()
        assert not outcome.primary_success
        assert outcome.error.code == "level_glyph_unsafe"
        assert "yoke projects capability-settings set" in outcome.error.message
