"""Lane resolution coverage for every session-registration entry path.

The regression these cover: a caller that could not resolve a lane locally
shipped the unresolved sentinel as an *explicit* lane, and the sentinel won
against the project's ``executor_default_lanes`` mapping. The stamped lane
then matched no ``lane_paths`` entry, so the offer gate treated the session
as unknown-lane and refused to route work to it — while sessions of the same
executor registered minutes apart through a path that carried no lane
resolved correctly.
"""

from __future__ import annotations

import pytest

from yoke_contracts.session_lane import (
    UNRESOLVED_EXECUTION_LANE,
    lane_is_unresolved,
)
from yoke_core.api.routing_config import (
    load_project_routing_settings,
    load_routing_config,
    resolve_execution_lane,
)

# The shape a project's session-routing capability declares: family
# wildcards over executor surfaces, and the lanes those families may run.
_PROJECT_ROUTING = {
    "executor_default_lane_claude*": "DARIUS",
    "executor_default_lane_codex*": "ALTMAN",
    "lane_paths_darius": "shepherd,conduct,dash",
    "lane_paths_altman": "refine,polish,dash",
}

# Every executor surface a live session registers under, and the lane the
# family wildcards above must resolve for it.
_EXECUTOR_LANES = [
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
    """The unresolved sentinel is not a lane and never outranks policy."""

    @pytest.mark.parametrize("executor,expected", _EXECUTOR_LANES)
    def test_relayed_sentinel_yields_to_executor_mapping(self, executor, expected):
        assert resolve_execution_lane(
            executor=executor,
            explicit_lane=UNRESOLVED_EXECUTION_LANE,
            routing_config=_routing(),
        ) == expected

    @pytest.mark.parametrize("executor,expected", _EXECUTOR_LANES)
    def test_absent_lane_resolves_the_same_as_the_sentinel(self, executor, expected):
        assert resolve_execution_lane(
            executor=executor, explicit_lane=None, routing_config=_routing(),
        ) == expected

    def test_sentinel_case_and_padding_still_yield(self):
        assert resolve_execution_lane(
            executor="claude-code",
            explicit_lane="  PRIMARY  ",
            routing_config=_routing(),
        ) == "DARIUS"

    def test_default_sentinel_still_yields(self):
        assert resolve_execution_lane(
            executor="codex", explicit_lane="default", routing_config=_routing(),
        ) == "ALTMAN"

    def test_real_explicit_lane_still_wins(self):
        assert resolve_execution_lane(
            executor="claude-code", explicit_lane="ALTMAN", routing_config=_routing(),
        ) == "ALTMAN"

    def test_unmapped_executor_reports_unresolved(self):
        resolved = resolve_execution_lane(
            executor="some-other-harness",
            explicit_lane=None,
            routing_config=_routing(),
        )
        assert lane_is_unresolved(resolved)
        assert resolved.upper() not in _routing().lane_allowed_paths


class TestStampedLaneIsRoutable:
    """A stamped lane must be one the project's allowlist declares."""

    @pytest.mark.parametrize("executor,expected", _EXECUTOR_LANES)
    def test_resolved_lane_is_declared_in_lane_paths(self, executor, expected):
        routing = _routing()
        resolved = resolve_execution_lane(
            executor=executor,
            explicit_lane=UNRESOLVED_EXECUTION_LANE,
            routing_config=routing,
        )
        assert resolved.upper() in routing.lane_allowed_paths
        assert resolved == expected

    def test_sentinel_is_absent_from_lane_paths(self):
        assert (
            UNRESOLVED_EXECUTION_LANE.upper()
            not in _routing().lane_allowed_paths
        )


class TestProjectLaneForExecutor:
    """The hook-registration resolver reads project policy at stamp time."""

    @pytest.mark.parametrize("executor,expected", _EXECUTOR_LANES)
    def test_resolves_each_executor_surface(self, executor, expected):
        from yoke_core.hooks.registration_identity import (
            project_lane_for_executor,
        )

        conn = _RoutingConn(
            '{"executor_default_lanes":{"claude*":"DARIUS","codex*":"ALTMAN"},'
            '"lane_paths":{"DARIUS":["dash"],"ALTMAN":["dash"]}}'
        )
        assert project_lane_for_executor(conn, 1, executor) == expected

    def test_relayed_sentinel_does_not_override_project_policy(self):
        from yoke_core.hooks.registration_identity import (
            project_lane_for_executor,
        )

        conn = _RoutingConn('{"executor_default_lanes":{"claude*":"DARIUS"}}')
        assert project_lane_for_executor(
            conn, 1, "claude-desktop", explicit_lane=UNRESOLVED_EXECUTION_LANE,
        ) == "DARIUS"

    def test_no_project_id_leaves_the_caller_in_charge(self):
        from yoke_core.hooks.registration_identity import (
            project_lane_for_executor,
        )

        assert project_lane_for_executor(None, None, "claude-code") is None


class TestProjectRoutingDefaults:
    """A project with no declared settings still resolves real lanes."""

    def test_missing_capability_row_keeps_family_wildcards(self):
        class _MissingRow:
            def execute(self, *_a, **_k) -> _Cursor:
                return _Cursor(None)

        settings = load_project_routing_settings(_MissingRow(), 1)
        routing = load_routing_config("", project_settings=settings)
        for executor, _expected in _EXECUTOR_LANES:
            assert not lane_is_unresolved(
                routing.default_lane_for_executor(executor)
            )
