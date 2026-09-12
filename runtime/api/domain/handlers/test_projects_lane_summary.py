"""The lane summary composes routing; the page it feeds only renders.

Composition matters because three answers on that screen are not stored
anywhere: a lane's effective label and glyph, which harnesses default to it,
and what each allowed action means. If the browser derived any of them it
would be a second implementation of precedence, so this handler owes the
page a finished answer and these cases are that contract.
"""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import json_helper
from yoke_core.domain.handlers import projects_lane_summary
from yoke_core.domain.handlers.projects_lane_summary import (
    handle_lane_summary_get,
)
from yoke_core.domain.routable_actions import routable_action_ids

_STORED = {
    "executor_default_lanes": {"claude*": "DARIUS", "codex*": "ALTMAN"},
    "lane_metadata": {
        "DARIUS": {"label": "DARIUS", "glyph": "\U0001f40e"},
        "ALTMAN": {"label": "SPECS", "glyph": "\U0001f453"},
        "MUSKY": {"label": "MUSKY", "glyph": "\U0001f6f8"},
    },
    "lane_paths": {
        "DARIUS": list(routable_action_ids()),
        "ALTMAN": ["refine", "polish"],
        "MUSKY": [],
    },
    "lane_rules": [
        {"harness": "cursor", "lane": "MUSKY"},
        {"model": "claude-opus-*", "lane": "DARIUS"},
        {"harness": "cursor", "model": "gpt-*", "lane": "ALTMAN"},
    ],
}


@pytest.fixture
def summary(monkeypatch):
    """Return the handler result for a project storing ``_STORED``.

    Routes through the real ``load_project_routing_settings`` against a
    DB-shaped row rather than mocking it away: that function is the one
    that flattens ``lane_rules``/``lane_metadata`` into JSON text, and it is
    exactly that flattened shape ``load_routing_config`` normalizes again.
    Mocking it out (as the fixture used to) skips the boundary the phantom
    lane defect lived on and would let a regression there go uncaught.
    """

    def _load(stored=_STORED, configured=True):
        stored_text = json_helper.dumps_compact(stored) if configured else None
        monkeypatch.setattr(
            "yoke_core.domain.projects_capabilities_settings"
            ".cmd_capability_get_settings",
            lambda *_a, **_k: stored_text,
        )
        monkeypatch.setattr(
            projects_lane_summary, "_authorized_project_ref", lambda *_a: "1"
        )

        class _Cursor:
            def __init__(self, row):
                self._row = row

            def fetchone(self):
                return self._row

        class _Conn:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def execute(self, *_a, **_k):
                row = None if stored_text is None else {"settings": stored_text}
                return _Cursor(row)

        monkeypatch.setattr(
            "yoke_core.domain.db_helpers.connect", lambda *_a, **_k: _Conn()
        )
        monkeypatch.setattr(
            "yoke_core.domain.project_identity.resolve_project_id",
            lambda *_a, **_k: 1,
        )
        outcome = handle_lane_summary_get(
            FunctionCallRequest(
                function="projects.lane_summary.get",
                actor=ActorContext(actor_id=None, session_id="lane-summary-test"),
                target=TargetRef(kind="global"),
                payload={"project": "yoke"},
            )
        )
        assert outcome.primary_success, outcome.error
        return outcome.result_payload

    return _load


def _lane(payload, lane_id):
    return next(row for row in payload["lanes"] if row["id"] == lane_id)


class TestLanePresentation:
    def test_a_lane_reports_its_configured_label_and_glyph(self, summary):
        lane = _lane(summary(), "ALTMAN")
        assert lane["label"] == "SPECS"
        assert lane["glyph"] == "\U0001f453"

    def test_the_stored_identity_is_reported_beside_the_label(self, summary):
        # Renaming presentation must not move the identity everything else
        # keys on, so the summary carries both.
        assert _lane(summary(), "ALTMAN")["id"] == "ALTMAN"

    def test_every_declared_lane_appears_once(self, summary):
        ids = [lane["id"] for lane in summary()["lanes"]]
        assert sorted(ids) == ["ALTMAN", "DARIUS", "MUSKY"]


class TestAllowedActions:
    def test_a_subset_is_reported_exactly(self, summary):
        assert _lane(summary(), "ALTMAN")["actions"] == ["refine", "polish"]

    def test_an_empty_allowlist_stays_empty(self, summary):
        # The page renders this as None; widening it here to "all" would
        # invert the operator's configuration before it reached the screen.
        assert _lane(summary(), "MUSKY")["actions"] == []

    def test_the_catalog_travels_with_the_summary(self, summary):
        catalog = summary()["action_catalog"]
        assert [row["id"] for row in catalog] == list(routable_action_ids())
        assert all(row["label"] and row["description"] for row in catalog)


class TestMatchesAndDefaults:
    def test_several_selectors_on_one_lane_are_all_reported(self, summary):
        assert _lane(summary(), "MUSKY")["matches"] == [
            {"lane": "MUSKY", "harness": "cursor", "model": None}
        ]
        assert _lane(summary(), "DARIUS")["matches"] == [
            {"lane": "DARIUS", "harness": None, "model": "claude-opus-*"}
        ]

    def test_a_lane_with_no_selector_reports_none(self, summary):
        assert _lane(summary(), "ALTMAN")["matches"] == [
            {"lane": "ALTMAN", "harness": "cursor", "model": "gpt-*"}
        ]

    def test_default_for_is_resolved_rather_than_read_from_a_key(self, summary):
        payload = summary()
        assert _lane(payload, "DARIUS")["default_for"] == ["Claude Code"]
        assert _lane(payload, "ALTMAN")["default_for"] == ["Codex"]

    def test_a_harness_only_rule_is_a_default_like_any_other(self, summary):
        # Cursor has no executor_default_lanes entry; its harness-only rule
        # is what routes it, and that is as much a default as the key would
        # have been.
        assert _lane(summary(), "MUSKY")["default_for"] == ["Cursor"]
        assert summary()["unrouted_harnesses"] == []

    def test_a_harness_nothing_routes_is_named_rather_than_omitted(self, summary):
        # Absent from every row reads like a lane nobody defaults to. The
        # real fact is a harness that cannot be routed at all, so it is
        # reported under its own name. Codex still resolves through the
        # session-routing baseline defaults merged beneath the stored
        # capability (real production behavior); only Cursor has neither a
        # default nor a rule in this configuration.
        payload = summary(
            stored={
                "lane_metadata": {"DARIUS": {"label": "DARIUS"}},
                "lane_paths": {"DARIUS": ["dash"]},
                "executor_default_lanes": {"claude*": "DARIUS"},
            }
        )
        assert payload["unrouted_harnesses"] == ["Cursor"]
        assert _lane(payload, "DARIUS")["default_for"] == ["Claude Code"]

    def test_the_harness_vocabulary_travels_with_the_summary(self, summary):
        assert summary()["harnesses"] == [
            {"id": "claude-code", "label": "Claude Code"},
            {"id": "codex", "label": "Codex"},
            {"id": "cursor", "label": "Cursor"},
        ]


class TestUnconfiguredProject:
    def test_a_project_with_no_stored_capability_says_so(self, summary):
        payload = summary(stored=_STORED, configured=False)
        assert payload["configured"] is False
        # An unset capability still routes — on defaults — so the summary
        # must not read as "no lanes".
        assert payload["lanes"]

    def test_a_stored_capability_is_reported_as_configured(self, summary):
        assert summary()["configured"] is True


class TestNoPhantomLanesFromDbShapedSettings:
    """``load_project_routing_settings`` flattens ``lane_rules`` and
    ``lane_metadata`` into JSON text before ``load_routing_config``
    normalizes the result a second time. A prior defect at that shared
    boundary double-encoded the already-flat text, so the single decode on
    read handed back the JSON string itself rather than the parsed object —
    iterating it in ``_declared_lanes`` yielded one phantom lane per
    character (``{``, a quote, letters, unicode escapes) alongside the real
    ones.
    """

    def test_only_real_lanes_are_reported(self, summary):
        ids = [lane["id"] for lane in summary()["lanes"]]
        assert sorted(ids) == ["ALTMAN", "DARIUS", "MUSKY"]
        # None of the JSON structural characters a broken decode would
        # have scattered across the lane list.
        assert not any(len(lane_id) == 1 for lane_id in ids)

    def test_lane_metadata_survives_the_round_trip(self, summary):
        lane = _lane(summary(), "MUSKY")
        assert lane["label"] == "MUSKY"
        assert lane["glyph"] == "\U0001f6f8"

    def test_lane_rules_survive_the_round_trip(self, summary):
        assert _lane(summary(), "MUSKY")["matches"] == [
            {"lane": "MUSKY", "harness": "cursor", "model": None}
        ]
