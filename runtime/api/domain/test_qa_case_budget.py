"""Execution-budget selection for registered Command QA cases."""

from yoke_core.domain import qa_case_budget


def test_full_local_suite_gets_an_hour_by_class() -> None:
    selected = qa_case_budget.resolve_command_case_budget(
        {"registered_scope": "full"}
    )

    assert selected.seconds == (
        qa_case_budget.FULL_SUITE_COMMAND_CASE_BUDGET_SECONDS
    )
    assert selected.source == "registered_scope:full"


def test_quick_local_suite_keeps_the_tight_local_budget() -> None:
    selected = qa_case_budget.resolve_command_case_budget(
        {"registered_scope": "quick"}
    )

    assert selected.seconds == qa_case_budget.DEFAULT_COMMAND_CASE_BUDGET_SECONDS
    assert selected.source == "registered_scope:quick"


def test_quick_ci_suite_outlasts_a_congested_actions_queue() -> None:
    """The CI budget is wall clock, so queueing alone cannot reap a run."""
    selected = qa_case_budget.resolve_command_case_budget(
        {"registered_scope": "quick"},
        runner_default=qa_case_budget.DEFAULT_CI_RUN_TIMEOUT_SECONDS,
    )

    assert selected.seconds == qa_case_budget.DEFAULT_CI_RUN_TIMEOUT_SECONDS
    assert selected.seconds > 20 * 60
    assert selected.source == "registered_scope:quick"


def test_method_config_wins_over_the_registered_class() -> None:
    selected = qa_case_budget.resolve_command_case_budget(
        {"registered_scope": "full", "timeout_seconds": 4000}
    )

    assert selected.seconds == 4000
    assert selected.source == "method_config"


def test_explicit_override_wins_over_every_default() -> None:
    selected = qa_case_budget.resolve_command_case_budget(
        {"registered_scope": "full", "timeout_seconds": 4000},
        explicit_override=33,
    )

    assert selected.seconds == 33
    assert selected.source == "explicit_override"
