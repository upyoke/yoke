"""Level resolution for a registering session.

Observed model and effort determine the highest model-specific threshold.
Launch stamps never override observed facts; unknown facts remain unresolved.
"""

from __future__ import annotations

import json

import pytest

from yoke_contracts.levels import default_levels, parse_levels
from yoke_contracts.session_level import (
    UNRESOLVED_EXECUTION_LEVEL,
    level_is_unresolved,
)
from yoke_core.domain.session_level_resolution import (
    resolve_execution_level,
    session_levels,
)
from yoke_contracts.model_level_resolution import (
    routing_effort_of,
    routing_model_of,
)
from yoke_core.hooks.registration_identity import project_level_for_session
from runtime.api.fixtures.level_store import levels_doc, option
from runtime.api.fixtures.model_catalog import RECORDS

# Every surface a live session registers under, with a shipped option for
# its family and the shipped level that option belongs to.
_SHIPPED_MATCHES = [
    ("claude-code", "claude-opus-5-5", "medium", "SENIOR"),
    ("claude-desktop", "claude-opus-5-5", "medium", "SENIOR"),
    ("claude", "claude-haiku-5-5", "max", "INTERN"),
    ("codex", "gpt-6-luna", "max", "INTERN"),
    ("codex-desktop", "gpt-6.1-sol", "medium", "SENIOR"),
]

_SPLIT_MODEL = "claude-sonnet-5-5"
_SPLIT_DOC = levels_doc(
    ("LOWER", [option(_SPLIT_MODEL, "high")]),
    ("UPPER", [option(_SPLIT_MODEL, "max")]),
)


def _resolve(executor, model, effort=None, *, explicit=None, levels=None):
    return resolve_execution_level(
        executor=executor,
        explicit_level=explicit,
        levels=default_levels() if levels is None else levels,
        model=model,
        reasoning_effort=effort,
        records=RECORDS,
    )


class TestShippedSchemeMatch:
    @pytest.mark.parametrize("executor,model,effort,expected", _SHIPPED_MATCHES)
    def test_each_surface_lands_on_its_option_level(
        self, executor, model, effort, expected
    ):
        assert _resolve(executor, model, effort) == expected

    @pytest.mark.parametrize("executor,model,effort,expected", _SHIPPED_MATCHES)
    def test_relayed_sentinel_yields_to_the_option_match(
        self, executor, model, effort, expected
    ):
        assert (
            _resolve(executor, model, effort, explicit=UNRESOLVED_EXECUTION_LEVEL)
            == expected
        )

    @pytest.mark.parametrize("explicit", ["  PRIMARY  ", "default", ""])
    def test_non_choices_yield_to_the_option_match(self, explicit):
        assert (
            _resolve("claude-code", "claude-opus-5-5", "medium", explicit=explicit)
            == "SENIOR"
        )

    def test_observed_model_overrides_explicit_launch_stamp(self):
        assert (
            _resolve("claude-code", "claude-opus-5-5", "medium", explicit="INTERN")
            == "SENIOR"
        )

    @pytest.mark.parametrize(
        "executor,model",
        [
            ("claude-code", "claude-unlisted-model"),
            ("claude-code", None),
        ],
    )
    def test_no_matching_option_reports_unresolved(self, executor, model):
        resolved = _resolve(executor, model, "medium")
        assert resolved == UNRESOLVED_EXECUTION_LEVEL
        assert level_is_unresolved(resolved)


class TestEffortDisambiguation:
    """One model listed at two efforts labels by the session's own effort."""

    @pytest.mark.parametrize(
        "effort,expected",
        [
            ("max", "UPPER"),
            ("MAX", "UPPER"),
            ("high", "LOWER"),
            ("medium", UNRESOLVED_EXECUTION_LEVEL),
            (None, UNRESOLVED_EXECUTION_LEVEL),
        ],
    )
    def test_effort_must_dominate_the_option(self, effort, expected):
        levels = parse_levels(_SPLIT_DOC)
        assert _resolve("claude-code", _SPLIT_MODEL, effort, levels=levels) == expected


class TestMatchInputs:
    def test_requested_context_suffix_is_stripped(self):
        model = routing_model_of(None, "claude-opus-5-5[1m]")
        assert model == "claude-opus-5-5"
        assert _resolve("claude-code", model, "medium") == "SENIOR"

    def test_served_model_outranks_the_ask(self):
        assert routing_model_of("claude-haiku-4-5", "claude-opus-5-5[1m]") == (
            "claude-haiku-4-5"
        )

    def test_nothing_known_names_no_model(self):
        assert routing_model_of(None, "  ") is None

    def test_served_effort_outranks_the_ask(self):
        assert routing_effort_of("MAX", "medium") == "max"
        assert routing_effort_of(None, "medium") == "medium"
        assert routing_effort_of(None, None) is None

    def test_no_connection_reads_the_shipped_scheme(self):
        assert session_levels(None, 1) == default_levels()


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _LevelStoreConn:
    """Answer the two level-store reads from in-memory documents."""

    def __init__(self, *, universe=None, project=None, raw_universe=None):
        self._universe = raw_universe if raw_universe is not None else _dump(universe)
        self._project = None if project is None else json.dumps({"levels": project})

    def execute(self, sql, *_args, **_kwargs):
        if "universe_settings" in sql:
            value = self._universe
        elif "project_capabilities" in sql:
            value = self._project
        elif "model_reference_revisions" in sql:
            return _Cursor(
                (
                    "fixture",
                    "1970-01-01T00:00:00Z",
                    "1970-01-01T00:00:00Z",
                    None,
                    json.dumps([record.to_dict() for record in RECORDS]),
                    "fixture",
                    None,
                )
            )
        else:
            raise AssertionError(f"unexpected query: {sql}")
        return _Cursor(None if value is None else (value,))


def _dump(document):
    return None if document is None else json.dumps(document)


_UNIVERSE_DOC = levels_doc(("UNIVERSE_ONLY", [option("claude-opus-5-5", "medium")]))
_PROJECT_DOC = levels_doc(("PROJECT_ONLY", [option("claude-opus-5-5", "medium")]))


class TestProjectLevelForSession:
    """The hook-registration resolver reads the level stores at stamp time."""

    def _level(self, conn, project_id=1, **kwargs):
        kwargs.setdefault("model", "claude-opus-5-5")
        kwargs.setdefault("reasoning_effort", "medium")
        return project_level_for_session(conn, project_id, "claude-code", **kwargs)

    def test_nothing_stored_reads_the_shipped_scheme(self):
        assert self._level(_LevelStoreConn()) == "SENIOR"

    def test_stored_universe_definition_replaces_the_shipped_scheme(self):
        assert self._level(_LevelStoreConn(universe=_UNIVERSE_DOC)) == "UNIVERSE_ONLY"

    def test_project_override_wins_over_the_universe(self):
        conn = _LevelStoreConn(universe=_UNIVERSE_DOC, project=_PROJECT_DOC)
        assert self._level(conn) == "PROJECT_ONLY"

    def test_relayed_sentinel_does_not_override_the_match(self):
        conn = _LevelStoreConn(universe=_UNIVERSE_DOC)
        assert (
            self._level(conn, explicit_level=UNRESOLVED_EXECUTION_LEVEL)
            == "UNIVERSE_ONLY"
        )

    def test_explicit_level_cannot_override_observed_model(self):
        conn = _LevelStoreConn(project=_PROJECT_DOC)
        assert self._level(conn, explicit_level="CHOSEN") == "PROJECT_ONLY"

    def test_unreadable_stored_document_labels_nothing(self):
        conn = _LevelStoreConn(raw_universe="{not json")
        assert self._level(conn) == UNRESOLVED_EXECUTION_LEVEL

    def test_no_project_and_no_model_reports_unresolved(self):
        assert (
            project_level_for_session(None, None, "claude-code")
            == UNRESOLVED_EXECUTION_LEVEL
        )
