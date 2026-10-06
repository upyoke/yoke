"""Level resolution coverage for every session-registration entry path.

The regression these cover: a caller that could not resolve a level locally
shipped the unresolved sentinel as an *explicit* level, and the sentinel won
against the project's ``executor_default_levels`` mapping. The stamped level
then reported no configured grouping — while sessions of the same
executor registered minutes apart through a path that carried no level
resolved correctly.
"""

from __future__ import annotations

import pytest

from yoke_contracts.session_level import (
    UNRESOLVED_EXECUTION_LEVEL,
    level_is_unresolved,
)
from yoke_core.api.routing_config import (
    load_project_routing_settings,
    load_routing_config,
    resolve_execution_level,
)

# The shape a project's session-routing capability declares: family
# wildcards over executor surfaces, and the levels those families may run.
_PROJECT_ROUTING = {
    "executor_default_level_claude*": "DARIUS",
    "executor_default_level_codex*": "ALTMAN",
}

# Every executor surface a live session registers under, and the level the
# family wildcards above must resolve for it.
_EXECUTOR_LEVELS = [
    ("claude-desktop", "DARIUS"),
    ("claude-code", "DARIUS"),
    ("claude", "DARIUS"),
    ("codex-desktop", "ALTMAN"),
    ("codex", "ALTMAN"),
]


def _routing():
    return load_routing_config("", project_settings=_PROJECT_ROUTING)


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _RoutingConn:
    """Minimal conn exposing one project's session-routing settings."""

    def __init__(self, settings_text: str):
        self._settings_text = settings_text

    def execute(self, *_args, **_kwargs) -> _Cursor:
        return _Cursor({"settings": self._settings_text})


class TestSentinelYieldsToProjectRouting:
    """The unresolved sentinel is not a level and never outranks policy."""

    @pytest.mark.parametrize("executor,expected", _EXECUTOR_LEVELS)
    def test_relayed_sentinel_yields_to_executor_mapping(self, executor, expected):
        assert (
            resolve_execution_level(
                executor=executor,
                explicit_level=UNRESOLVED_EXECUTION_LEVEL,
                routing_config=_routing(),
            )
            == expected
        )

    @pytest.mark.parametrize("executor,expected", _EXECUTOR_LEVELS)
    def test_absent_level_resolves_the_same_as_the_sentinel(self, executor, expected):
        assert (
            resolve_execution_level(
                executor=executor,
                explicit_level=None,
                routing_config=_routing(),
            )
            == expected
        )

    def test_sentinel_case_and_padding_still_yield(self):
        assert (
            resolve_execution_level(
                executor="claude-code",
                explicit_level="  PRIMARY  ",
                routing_config=_routing(),
            )
            == "DARIUS"
        )

    def test_default_sentinel_still_yields(self):
        assert (
            resolve_execution_level(
                executor="codex",
                explicit_level="default",
                routing_config=_routing(),
            )
            == "ALTMAN"
        )

    def test_real_explicit_level_still_wins(self):
        assert (
            resolve_execution_level(
                executor="claude-code",
                explicit_level="ALTMAN",
                routing_config=_routing(),
            )
            == "ALTMAN"
        )

    def test_unmapped_executor_reports_unresolved(self):
        resolved = resolve_execution_level(
            executor="some-other-harness",
            explicit_level=None,
            routing_config=_routing(),
        )
        assert level_is_unresolved(resolved)


class TestProjectLevelForSession:
    """The hook-registration resolver reads project policy at stamp time."""

    @pytest.mark.parametrize("executor,expected", _EXECUTOR_LEVELS)
    def test_resolves_each_executor_surface(self, executor, expected):
        from yoke_core.hooks.registration_identity import (
            project_level_for_session,
        )

        conn = _RoutingConn(
            '{"executor_default_levels":{"claude*":"DARIUS","codex*":"ALTMAN"},'
            '"level_metadata":{"DARIUS":{},"ALTMAN":{}}}'
        )
        assert project_level_for_session(conn, 1, executor) == expected

    def test_relayed_sentinel_does_not_override_project_policy(self):
        from yoke_core.hooks.registration_identity import (
            project_level_for_session,
        )

        conn = _RoutingConn('{"executor_default_levels":{"claude*":"DARIUS"}}')
        assert (
            project_level_for_session(
                conn,
                1,
                "claude-desktop",
                explicit_level=UNRESOLVED_EXECUTION_LEVEL,
            )
            == "DARIUS"
        )

    def test_no_project_id_leaves_the_caller_in_charge(self):
        from yoke_core.hooks.registration_identity import (
            project_level_for_session,
        )

        assert project_level_for_session(None, None, "claude-code") is None


class TestProjectRoutingDefaults:
    """A project with no declared settings still resolves real levels."""

    def test_missing_capability_row_keeps_family_wildcards(self):
        class _MissingRow:
            def execute(self, *_a, **_k) -> _Cursor:
                return _Cursor(None)

        settings = load_project_routing_settings(_MissingRow(), 1)
        routing = load_routing_config("", project_settings=settings)
        for executor, _expected in _EXECUTOR_LEVELS:
            assert not level_is_unresolved(routing.default_level_for_executor(executor))
