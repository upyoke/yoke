"""The execution-levels contract: validation, labeling, and precedence."""

from __future__ import annotations

import copy

import pytest

from yoke_contracts.level_defaults import DEFAULT_LEVELS
from yoke_contracts.levels import (
    LevelsError,
    default_levels,
    level_for_session,
    level_presentation,
    levels_payload,
    parse_levels,
    resolve_effective_levels,
)


def _option(surface="claude-cli", model="claude-opus-5-5", effort="medium", **extra):
    return {
        "surface": surface,
        "model": model,
        "reasoning_effort": effort,
        "context_window_tokens": None,
        **extra,
    }


def _doc(*levels):
    return [
        {"name": name, "glyph": glyph, "options": options}
        for name, glyph, options in levels
    ]


def _refusal(document) -> LevelsError:
    with pytest.raises(LevelsError) as caught:
        parse_levels(document)
    return caught.value


class TestShippedScheme:
    def test_the_shipped_scheme_validates_lowest_first(self):
        assert [level.name for level in default_levels()] == [
            "INTERN",
            "JUNIOR",
            "SENIOR",
            "PRINCIPAL",
        ]

    def test_the_shipped_scheme_round_trips_through_its_payload(self):
        payload = levels_payload(default_levels())
        assert parse_levels(payload) == default_levels()
        assert payload == [dict(level) for level in DEFAULT_LEVELS]

    def test_the_cursor_option_carries_its_same_surface_fallback(self):
        junior = default_levels()[1]
        cursor = junior.options[0]
        assert (cursor.surface, cursor.model, cursor.reasoning_effort) == (
            "cursor-cli",
            "grok-4.7-high",
            "high",
        )
        assert cursor.fallback is not None
        assert cursor.fallback.model == "claude-opus-5-5-medium"

    def test_claude_options_accept_xhigh_and_a_one_million_window(self):
        principal = default_levels()[3]
        assert principal.options[0].reasoning_effort == "xhigh"
        assert principal.options[0].context_window_tokens == 1_000_000


class TestRefusals:
    @pytest.mark.parametrize("model", ["claude-opus-*", "", "*"])
    def test_a_wildcard_or_blank_model_is_not_launchable(self, model):
        error = _refusal(_doc(("A", "\U0001f40e", [_option(model=model)])))
        assert error.code == "level_option_model_not_launchable"
        assert error.field == "levels[0].options[0].model"

    def test_an_effort_the_surface_does_not_accept_is_refused_by_name(self):
        error = _refusal(_doc(("A", "\U0001f40e", [_option(effort="ultra")])))
        assert error.code == "claude_reasoning_effort_unsupported"
        assert "accepted: low, medium, high, xhigh, max" in error.detail

    def test_a_context_window_the_surface_cannot_pass_is_refused(self):
        option = _option("codex-cli", "gpt-6.1-sol", context_window_tokens=1_000_000)
        error = _refusal(_doc(("A", "\U0001f40e", [option])))
        assert error.code == "codex_context_window_unsupported"

    def test_a_cursor_selector_encoding_another_effort_is_refused(self):
        option = _option("cursor-cli", "grok-4.7-high", "low")
        error = _refusal(_doc(("A", "\U0001f40e", [option])))
        assert error.code == "cursor_reasoning_effort_conflict"

    def test_an_option_without_effort_is_refused(self):
        error = _refusal(_doc(("A", "\U0001f40e", [_option(effort="")])))
        assert error.code == "level_option_effort_required"

    def test_an_unknown_surface_is_refused(self):
        error = _refusal(_doc(("A", "\U0001f40e", [_option(surface="vim-cli")])))
        assert error.code == "level_option_surface_unsupported"

    def test_a_fallback_on_another_surface_is_refused(self):
        option = _option(fallback=_option("codex-cli", "gpt-6.1-sol"))
        error = _refusal(_doc(("A", "\U0001f40e", [option])))
        assert error.code == "level_option_fallback_surface"

    def test_a_fallback_cannot_nest(self):
        inner = _option(model="claude-haiku-4-5", fallback=_option(model="x-model"))
        error = _refusal(_doc(("A", "\U0001f40e", [_option(fallback=inner)])))
        assert error.code == "level_option_fallback_nested"

    def test_one_selection_cannot_label_two_levels(self):
        error = _refusal(
            _doc(
                ("A", "\U0001f40e", [_option()]),
                ("B", "\U0001f453", [_option()]),
            )
        )
        assert error.code == "level_option_duplicate"
        assert "already belongs to A" in error.detail

    @pytest.mark.parametrize(
        "name,code",
        [("senior", "level_name_invalid"), ("primary", "level_name_invalid")],
    )
    def test_a_name_must_be_canonical_and_not_reserved(self, name, code):
        assert _refusal(_doc((name, "\U0001f40e", [_option()]))).code == code

    def test_a_duplicate_name_is_refused(self):
        error = _refusal(
            _doc(
                ("A", "\U0001f40e", [_option()]),
                ("A", "\U0001f453", [_option(model="claude-haiku-4-5")]),
            )
        )
        assert error.code == "level_name_duplicate"

    def test_an_unsafe_glyph_is_refused(self):
        assert _refusal(_doc(("A", "⚠", [_option()]))).code == "level_glyph_unsafe"

    @pytest.mark.parametrize("document", [[], {}, "INTERN", None])
    def test_a_document_must_be_a_non_empty_list(self, document):
        assert _refusal(document).code == "levels_document_invalid"

    def test_a_level_needs_an_option(self):
        assert _refusal(_doc(("A", "\U0001f40e", []))).code == "level_options_missing"

    def test_an_unknown_option_key_is_refused(self):
        option = _option(pools=["claude-weekly"])
        assert _refusal(_doc(("A", "\U0001f40e", [option]))).code == (
            "levels_document_invalid"
        )


class TestLabeling:
    @pytest.mark.parametrize(
        "executor", ["claude-code", "claude-cli", "claude-desktop"]
    )
    def test_every_claude_surface_matches_a_claude_option(self, executor):
        assert (
            level_for_session(
                default_levels(), executor=executor, model="claude-opus-5-5"
            )
            == "SENIOR"
        )

    def test_a_fallback_selection_labels_its_level(self):
        assert (
            level_for_session(
                default_levels(), executor="cursor", model="claude-opus-5-5-medium"
            )
            == "JUNIOR"
        )

    def test_a_model_no_option_names_is_unlabeled(self):
        assert (
            level_for_session(default_levels(), executor="codex", model="gpt-4o")
            is None
        )

    def test_the_harness_must_match_as_well_as_the_model(self):
        assert (
            level_for_session(
                default_levels(), executor="codex", model="claude-opus-5-5"
            )
            is None
        )

    @pytest.mark.parametrize("executor", [None, "", "emacs"])
    def test_an_unplaceable_executor_is_unlabeled(self, executor):
        assert (
            level_for_session(default_levels(), executor=executor, model="gpt-6-luna")
            is None
        )

    def test_effort_picks_between_levels_listing_one_model(self):
        levels = parse_levels(
            _doc(
                ("LOW", "\U0001f40e", [_option(effort="low")]),
                ("HIGH", "\U0001f453", [_option(effort="max")]),
            )
        )
        facts = {"executor": "claude-code", "model": "claude-opus-5-5"}
        assert level_for_session(levels, **facts, reasoning_effort="max") == "HIGH"
        assert level_for_session(levels, **facts, reasoning_effort="low") == "LOW"
        assert level_for_session(levels, **facts) == "LOW"
        assert level_for_session(levels, **facts, reasoning_effort="high") == "LOW"


class TestPrecedenceAndPresentation:
    def _custom(self):
        return _doc(("ONLY", "\U0001f680", [_option()]))

    def test_a_project_override_wins(self):
        levels, source = resolve_effective_levels(
            {"levels": self._custom()}, levels_payload(default_levels())
        )
        assert (source, [level.name for level in levels]) == ("project", ["ONLY"])

    def test_the_universe_document_wins_over_the_shipped_scheme(self):
        levels, source = resolve_effective_levels(None, self._custom())
        assert (source, levels[0].name) == ("universe", "ONLY")

    def test_the_shipped_scheme_is_the_last_answer(self):
        levels, source = resolve_effective_levels({}, None)
        assert (source, levels) == ("default", default_levels())

    def test_presentation_reads_the_glyph_and_keeps_an_unknown_name(self):
        assert level_presentation(default_levels(), "SENIOR") == {
            "label": "SENIOR",
            "glyph": "\U0001f989",
        }
        assert level_presentation(default_levels(), "DARIUS") == {
            "label": "DARIUS",
            "glyph": "",
        }

    def test_the_shipped_document_is_not_mutated_by_parsing(self):
        before = copy.deepcopy(list(DEFAULT_LEVELS))
        default_levels()
        assert list(DEFAULT_LEVELS) == before
