"""Tests for ``yoke_core.tools.watch_qa_plan``."""

from __future__ import annotations

import pytest

from yoke_contracts.watch_cli_forms import cli_form
from yoke_core.tools import watch_qa_plan
from yoke_core.tools._watch_runner import filter_match
from yoke_core.tools._watch_throttle import LineClass
from yoke_core.tools.watch_entrypoints import WRAPPER_MAINS
from yoke_core.tools.watch_tail import EXIT_SENTINEL
from yoke_cli.commands.watchers import TOOL_SHAPED_USAGE


class TestPlanClassifier:
    @pytest.mark.parametrize(
        "line",
        [
            '{"event": "machine_qa.operator_gate", "self_approving": true}',
            "host_baseline=fresh-host",
            "requirement=13625 case_key=welcome-frame",
            '{"checkpoint": "review-frame"}',
        ],
    )
    def test_plan_signals_are_progress(self, line: str) -> None:
        assert watch_qa_plan.classify_qa_plan_line(line).cls is LineClass.PROGRESS

    @pytest.mark.parametrize(
        "line",
        [
            "# qa plan run: requirement=13625 outcome=failed",
            "state awaiting_agent_review",
            "QA capture complete; dispatch the returned typed reviewer contract",
            '{"state": "awaiting_agent_review"}',
        ],
    )
    def test_outcome_and_review_handoff_are_summary(self, line: str) -> None:
        assert watch_qa_plan.classify_qa_plan_line(line).cls is LineClass.SUMMARY

    def test_engine_failures_are_urgent(self) -> None:
        assert watch_qa_plan.classify_qa_plan_line(
            "yoke qa plan run: TREE-BINDING REFUSAL"
        ).cls is LineClass.URGENT

    def test_unrelated_lines_are_noise(self) -> None:
        assert watch_qa_plan.classify_qa_plan_line("debug spam").cls is LineClass.NOISE

    def test_public_union_matches_classified_lines(self) -> None:
        assert filter_match(
            watch_qa_plan.QA_PLAN_PROGRESS_PATTERN,
            "machine_qa.operator_gate",
        )


def test_kind_matches_the_exit_sentinel() -> None:
    assert EXIT_SENTINEL.match(f"# watch_{watch_qa_plan.KIND} exit=0")
    assert EXIT_SENTINEL.match(f"# watch_{watch_qa_plan.KIND} exit=12")


def test_nested_invocation_is_rejected() -> None:
    assert watch_qa_plan._is_nested_invocation(
        ["yoke", "qa", "plan", "run", "--item", "YOK-1"]
    )
    assert not watch_qa_plan._is_nested_invocation(
        ["--item", "YOK-1", "--transition", "implemented"]
    )


def test_wrapper_is_registered() -> None:
    assert cli_form(watch_qa_plan.WRAPPER_MODULE) == "yoke watch qa-plan"
    assert WRAPPER_MAINS[watch_qa_plan.WRAPPER_MODULE] is watch_qa_plan.main
    assert "yoke watch qa-plan" in TOOL_SHAPED_USAGE
