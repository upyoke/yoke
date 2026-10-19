"""Static packet setup teaching points to the live facts owner."""

from yoke_core.domain.schema_api_context_main_agent_hints import (
    MAIN_AGENT_HINTS,
    SETUP_FACTS_HINT,
)


def test_setup_hint_has_read_recipe_status_meanings_and_no_live_facts():
    assert MAIN_AGENT_HINTS.count(SETUP_FACTS_HINT) == 1
    for text in (
        "yoke onboard checklist get --json",
        "run.next_action",
        "run.setup_readiness",
        "Configured",
        "verified",
        "deferred",
        "not-needed",
        "unknown",
        "blocked",
    ):
        assert text in SETUP_FACTS_HINT
    assert len(SETUP_FACTS_HINT) < 800
