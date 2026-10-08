"""Session level resolution inputs and the machine config path helper."""

from pathlib import Path

import pytest

from yoke_contracts.levels import default_levels
from yoke_core.api.routing_config import (
    config_path_from_db_path,
    resolve_execution_level,
    routing_effort_of,
    routing_model_of,
    session_levels,
)


def test_config_path_from_db_path_points_at_sibling_config(tmp_path):
    db_path = tmp_path / "runtime" / "yoke.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("", encoding="utf-8")

    assert (
        config_path_from_db_path(db_path)
        == Path(tmp_path / "runtime" / "config").resolve()
    )


class TestMatchingFacts:
    def test_an_attested_model_wins_over_the_ask(self):
        assert routing_model_of("claude-opus-5-5", "claude-haiku-4-5") == (
            "claude-opus-5-5"
        )

    def test_the_ask_is_the_fallback_with_its_context_tier_removed(self):
        assert routing_model_of(None, "claude-opus-5-5[1m]") == "claude-opus-5-5"

    def test_neither_model_fact_yields_none(self):
        assert routing_model_of("", "  ") is None

    def test_an_attested_effort_wins_and_is_folded(self):
        assert routing_effort_of("HIGH", "low") == "high"
        assert routing_effort_of(None, "max") == "max"
        assert routing_effort_of(None, None) is None


class TestResolution:
    @pytest.mark.parametrize("explicit", [None, "", "default", "primary", "PRIMARY"])
    def test_a_non_choice_yields_to_the_option_match(self, explicit):
        assert (
            resolve_execution_level(
                executor="codex",
                explicit_level=explicit,
                levels=default_levels(),
                model="gpt-6-astra",
            )
            == "PRINCIPAL"
        )

    def test_a_real_explicit_level_wins(self):
        assert (
            resolve_execution_level(
                executor="codex",
                explicit_level="SENIOR",
                levels=default_levels(),
                model="gpt-6-astra",
            )
            == "SENIOR"
        )

    def test_no_matching_option_stamps_the_unresolved_sentinel(self):
        assert (
            resolve_execution_level(
                executor="codex",
                explicit_level=None,
                levels=default_levels(),
                model=None,
            )
            == "primary"
        )

    def test_without_a_connection_the_shipped_scheme_labels(self):
        assert session_levels(None, None) == default_levels()
