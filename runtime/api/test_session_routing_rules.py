"""Selector routing: every tier, and the guarantee that order does not matter.

``lane_rules`` exists because ``executor_default_lanes`` can only answer
per harness. The risk it introduces is a resolution order an operator
cannot predict, so most of what is asserted here is that the answer depends
on how specific a selector is and on nothing else — not on list position,
not on which entry was added first.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.session_routing_rules import (
    LaneRule,
    LaneRuleError,
    parse_lane_rules,
    parse_lane_rules_for_routing,
    resolve_rule_lane,
    routing_model_of,
)

_LANES = ("DARIUS", "ALTMAN", "MUSKY")


def _rules(*entries):
    return parse_lane_rules(list(entries), declared_lanes=_LANES)


class TestTierPrecedence:
    """Explicit override sits above these; the rest is specificity."""

    def test_harness_and_model_outranks_model_alone(self):
        rules = _rules(
            {"model": "gpt-5", "lane": "DARIUS"},
            {"harness": "cursor", "model": "gpt-5", "lane": "ALTMAN"},
        )
        assert resolve_rule_lane(
            rules, executor="cursor-cli", model="gpt-5"
        ) == "ALTMAN"

    def test_model_alone_outranks_harness_alone(self):
        rules = _rules(
            {"harness": "cursor", "lane": "DARIUS"},
            {"model": "gpt-5", "lane": "ALTMAN"},
        )
        assert resolve_rule_lane(
            rules, executor="cursor-cli", model="gpt-5"
        ) == "ALTMAN"

    def test_harness_alone_applies_when_no_model_selector_matches(self):
        rules = _rules(
            {"harness": "cursor", "lane": "MUSKY"},
            {"model": "claude-opus-*", "lane": "DARIUS"},
        )
        assert resolve_rule_lane(
            rules, executor="cursor-cli", model="gpt-5"
        ) == "MUSKY"

    def test_no_match_leaves_the_harness_default_in_charge(self):
        rules = _rules({"harness": "codex", "lane": "ALTMAN"})
        assert resolve_rule_lane(
            rules, executor="claude-cli", model="claude-opus-5"
        ) is None


class TestModelSpecificity:
    def test_exact_model_outranks_a_prefix_that_also_matches(self):
        rules = _rules(
            {"model": "claude-opus-*", "lane": "DARIUS"},
            {"model": "claude-opus-5", "lane": "ALTMAN"},
        )
        assert resolve_rule_lane(
            rules, executor="claude-cli", model="claude-opus-5"
        ) == "ALTMAN"

    def test_longer_prefix_outranks_shorter(self):
        rules = _rules(
            {"model": "claude-*", "lane": "DARIUS"},
            {"model": "claude-opus-*", "lane": "MUSKY"},
        )
        assert resolve_rule_lane(
            rules, executor="claude-cli", model="claude-opus-5"
        ) == "MUSKY"

    def test_a_prefix_as_long_as_the_identifier_still_loses_to_it(self):
        # Both patterns are the same length; the exact form is still the
        # narrower claim, so length alone must not decide.
        rules = _rules(
            {"model": "claude-opus-*", "lane": "DARIUS"},
            {"model": "claude-opus-", "lane": "ALTMAN"},
        )
        assert resolve_rule_lane(
            rules, executor="claude-cli", model="claude-opus-"
        ) == "ALTMAN"


class TestOrderIndependence:
    @pytest.mark.parametrize("reverse", [False, True])
    def test_the_same_selectors_route_the_same_either_way_round(self, reverse):
        entries = [
            {"harness": "cursor", "lane": "MUSKY"},
            {"model": "claude-opus-*", "lane": "DARIUS"},
            {"harness": "cursor", "model": "gpt-*", "lane": "ALTMAN"},
        ]
        rules = parse_lane_rules(
            list(reversed(entries)) if reverse else entries,
            declared_lanes=_LANES,
        )
        assert resolve_rule_lane(
            rules, executor="cursor-cli", model="gpt-5"
        ) == "ALTMAN"
        assert resolve_rule_lane(
            rules, executor="cursor-cli", model="sonar"
        ) == "MUSKY"
        assert resolve_rule_lane(
            rules, executor="claude-cli", model="claude-opus-5"
        ) == "DARIUS"


class TestHarnessCanonicalization:
    @pytest.mark.parametrize(
        "executor", ["claude-code", "claude-cli", "claude-desktop", "claude"],
    )
    def test_every_claude_surface_matches_the_family_selector(self, executor):
        rules = _rules({"harness": "claude-code", "lane": "DARIUS"})
        assert resolve_rule_lane(rules, executor=executor, model=None) == "DARIUS"

    def test_an_unplaceable_executor_matches_no_harness_selector(self):
        rules = _rules({"harness": "claude-code", "lane": "DARIUS"})
        assert resolve_rule_lane(rules, executor="mystery", model=None) is None

    def test_an_unsupported_harness_selector_is_refused_at_parse(self):
        with pytest.raises(LaneRuleError) as caught:
            _rules({"harness": "emacs", "lane": "DARIUS"})
        assert "unsupported harness" in str(caught.value)
        assert "claude-code" in str(caught.value)


class TestMissingModel:
    def test_a_session_with_no_model_matches_only_harness_selectors(self):
        rules = _rules(
            {"model": "claude-opus-*", "lane": "DARIUS"},
            {"harness": "claude-code", "lane": "MUSKY"},
        )
        assert resolve_rule_lane(
            rules, executor="claude-cli", model=None
        ) == "MUSKY"

    def test_a_model_only_document_leaves_a_modelless_session_unrouted(self):
        rules = _rules({"model": "claude-opus-*", "lane": "DARIUS"})
        assert resolve_rule_lane(rules, executor="claude-cli", model=None) is None


class TestRoutingModel:
    def test_an_attested_model_wins_over_the_ask(self):
        assert routing_model_of("claude-opus-5", "claude-sonnet-5") == (
            "claude-opus-5"
        )

    def test_the_ask_is_the_fallback_with_its_context_tier_removed(self):
        assert routing_model_of(None, "claude-opus-5[1m]") == "claude-opus-5"

    def test_neither_fact_yields_no_model(self):
        assert routing_model_of(None, None) is None
        assert routing_model_of("", "  ") is None


class TestRefusedDocuments:
    def test_a_duplicate_selector_is_refused_and_names_the_other_lane(self):
        with pytest.raises(LaneRuleError) as caught:
            _rules(
                {"harness": "cursor", "lane": "MUSKY"},
                {"harness": "cursor", "lane": "ALTMAN"},
            )
        assert "repeats a selector" in str(caught.value)
        assert "MUSKY" in str(caught.value)

    def test_a_rule_naming_an_undeclared_lane_is_refused(self):
        with pytest.raises(LaneRuleError) as caught:
            _rules({"harness": "cursor", "lane": "NOWHERE"})
        assert "does not declare" in str(caught.value)

    @pytest.mark.parametrize(
        "model", ["cla*ude", "*-opus", "*", "cl*ude*"],
    )
    def test_a_malformed_model_pattern_is_refused(self, model):
        with pytest.raises(LaneRuleError) as caught:
            _rules({"model": model, "lane": "DARIUS"})
        assert "$" not in str(caught.value)
        assert caught.value.field.endswith(".model")

    def test_a_rule_matching_everything_is_refused(self):
        with pytest.raises(LaneRuleError) as caught:
            _rules({"lane": "DARIUS"})
        assert "matches nothing" in str(caught.value)

    def test_an_unsupported_key_is_refused_by_name(self):
        with pytest.raises(LaneRuleError) as caught:
            _rules({"harness": "cursor", "lane": "MUSKY", "priority": 3})
        assert "priority" in str(caught.value)

    def test_a_non_list_document_is_refused(self):
        with pytest.raises(LaneRuleError):
            parse_lane_rules({"harness": "cursor"}, declared_lanes=_LANES)


class TestReadPathLeniency:
    """Routing degrades to the harness default; it never refuses a session."""

    def test_an_unusable_entry_is_dropped_and_the_rest_still_route(self):
        rules = parse_lane_rules_for_routing(
            [
                {"harness": "emacs", "lane": "DARIUS"},
                {"harness": "cursor", "lane": "MUSKY"},
            ]
        )
        assert rules == (LaneRule(lane="MUSKY", harness="cursor"),)

    def test_a_document_of_the_wrong_shape_yields_no_rules(self):
        assert parse_lane_rules_for_routing("cursor=MUSKY") == ()

    def test_the_read_path_does_not_re_litigate_lane_declaration(self):
        # Declaration is the settings validator's job. Re-checking it here
        # would turn a stored document into a registration failure.
        rules = parse_lane_rules_for_routing(
            [{"harness": "cursor", "lane": "UNDECLARED"}]
        )
        assert rules[0].lane == "UNDECLARED"
