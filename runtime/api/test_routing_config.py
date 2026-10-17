"""Session level resolution inputs and the machine config path helper."""

from pathlib import Path

import pytest

from yoke_contracts.levels import default_levels
from runtime.api.fixtures.model_catalog import RECORDS
from yoke_core.api.routing_config import config_path_from_db_path
from yoke_core.domain.session_level_resolution import (
    resolve_execution_level,
    session_levels,
)
from yoke_contracts.model_level_resolution import (
    routing_effort_of,
    routing_model_of,
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

    def test_observed_cursor_effort_wins_over_requested_effort(self):
        assert routing_effort_of(None, "low", "grok-4.7-high-fast") == "high"


class TestResolution:
    @pytest.mark.parametrize("explicit", [None, "", "default", "primary", "PRIMARY"])
    def test_a_non_choice_yields_to_the_option_match(self, explicit):
        assert (
            resolve_execution_level(
                executor="codex",
                explicit_level=explicit,
                levels=default_levels(),
                records=RECORDS,
                model="gpt-6-astra",
                reasoning_effort="xhigh",
            )
            == "PRINCIPAL"
        )

    def test_actual_facts_win_over_a_real_launch_stamp(self):
        assert (
            resolve_execution_level(
                executor="codex",
                explicit_level="SENIOR",
                levels=default_levels(),
                records=RECORDS,
                model="gpt-6-astra",
                reasoning_effort="xhigh",
            )
            == "PRINCIPAL"
        )

    def test_no_matching_option_stamps_the_unresolved_sentinel(self):
        assert (
            resolve_execution_level(
                executor="codex",
                explicit_level=None,
                levels=default_levels(),
                records=RECORDS,
                model=None,
            )
            == "primary"
        )

    def test_without_a_connection_the_shipped_scheme_labels(self):
        assert session_levels(None, None) == default_levels()
