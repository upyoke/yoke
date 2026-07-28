"""QA schema examples in rendered agent packets."""

from __future__ import annotations

import pytest

from yoke_core.domain import schema_api_context as sac


def test_main_agent_packet_teaches_qa_requirement_run_columns() -> None:
    body = sac.render_role_packet("main_agent")
    for text in (
        "yoke qa requirement list --item PREFIX-N",
        "yoke qa run list --requirement-id <id>",
        "yoke qa run get --run-id <id>",
        "qa_requirements.id is the PK",
        "qa_runs.qa_requirement_id is the FK",
        "raw_result (result payload)",
    ):
        assert text in body
    assert "requirement_id, success_policy" not in body
    assert "SELECT id, requirement_id, result" not in body


def test_qa_packet_lists_live_qa_requirements_columns() -> None:
    body = sac.render_topic_packet("qa")
    for column in (
        "deployment_run_id",
        "target_env",
        "capability_requirements",
        "suite_id",
        "waived_at",
        "waiver_rationale",
        "waiver_source",
        "plan_id",
        "plan_case_key",
        "case_position",
        "baseline_position",
        "method_id",
        "method_name",
        "executor_id",
        "required_capability_kind",
        "verdict_path",
        "host_baseline",
        "entry_surface",
        "required_completion",
        "workflow_transition_id",
        "instructions",
        "expected_outcome",
        "method_config",
    ):
        assert column in body, (
            f"qa_requirements column {column!r} missing from qa packet"
        )


def test_qa_packet_lists_live_qa_runs_columns() -> None:
    body = sac.render_topic_packet("qa")
    for column in (
        "score",
        "confidence",
        "duration_ms",
        "started_at",
        "completed_at",
        "execution_status",
    ):
        assert column in body, f"qa_runs column {column!r} missing from qa packet"
    assert "execution_status` is the browser capture outcome" in body


def test_qa_packet_carries_canonical_unsatisfied_verification_select() -> None:
    body = sac.render_topic_packet("qa")
    assert "Canonical unsatisfied-verification SELECT" in body
    assert "FROM qa_requirements qr WHERE qr.item_id = %s" in body
    assert "qr.qa_phase = 'verification' AND qr.waived_at IS NULL" in body
    assert "NOT EXISTS (SELECT 1 FROM qa_runs qrun" in body
    assert "qrun.qa_requirement_id = qr.id AND qrun.verdict = 'pass'" in body


def test_qa_packet_carries_requirement_add_ac_verification_example() -> None:
    body = sac.render_topic_packet("qa")
    assert "Add a QA requirement — ac_verification variant" in body
    assert (
        "yoke qa requirement add "
        "--item PREFIX-N --qa-kind ac_verification --qa-phase verification "
        "--blocking-mode blocking --requirement-source ac_derived "
        "--workflow-transition reviewed-implementation"
    ) in body
    assert "`--workflow-transition` is required" in body
    assert "precedes a qa_verification gate" in body
    assert '{"min_runs":N,"min_pass":N}' in body
    assert "every row must include `workflow_transition_id`" in body
    # Epic-task / deployment-run attachment stays operator-debug; only the
    # deployment-run form may omit a workflow binding.
    assert (
        "requirement-add --epic-id E --task-num K --workflow-transition STAGE"
    ) in body
    assert "Deployment-run attachment is operator-debug only" in body
    assert "may omit the transition" in body


@pytest.mark.parametrize("role", ("engineer_agent", "tester_agent"))
def test_qa_executor_packets_require_transition_bound_creation(role: str) -> None:
    body = sac.render_role_packet(role)
    assert (
        "yoke qa requirement add "
        "--item PREFIX-N --qa-kind ac_verification --qa-phase verification "
        "--blocking-mode blocking --requirement-source ac_derived "
        "--workflow-transition reviewed-implementation"
    ) in body
    assert "every row must include `workflow_transition_id`" in body
    assert (
        "requirement-add --epic-id E --task-num K --workflow-transition STAGE"
    ) in body


def test_qa_packet_carries_plan_case_materialization_example() -> None:
    body = sac.render_topic_packet("qa")
    assert "Materialize attached QA plan cases for a transition" in body
    assert (
        "yoke qa plan materialize --item PREFIX-N --transition reviewed-implementation"
    ) in body
    for field in (
        "method_id",
        "expected_outcome",
        "immutable method_config",
    ):
        assert field in body


def test_qa_packet_carries_run_add_agent_ac_verification_example() -> None:
    body = sac.render_topic_packet("qa")
    assert "Add a QA run verdict — agent × ac_verification (inline raw_result)" in body
    assert (
        "yoke qa run add "
        "--requirement-id R --executor-type agent "
        "--qa-kind ac_verification --verdict pass "
    ) in body
    assert "`--qa-kind` defaults to the requirement's kind" in body


def test_qa_packet_carries_per_requirement_browser_case_run_example() -> None:
    body = sac.render_topic_packet("qa")
    assert "Execute one materialized Browser method case" in body
    assert (
        "yoke qa case run --requirement-id R "
        "--base-url https://preview.example "
        "--expected-branch BRANCH --expected-sha SHA"
    ) in body
    assert "qa.case_execution.begin" in body
    assert "executes only requirement R" in body
    assert "browser-check decides automatically" in body
    assert "browser-inspection records inconclusive evidence" in body


def test_qa_packet_carries_ordered_plan_run_example() -> None:
    body = sac.render_topic_packet("qa")
    assert "Execute an item's materialized QA plans in snapshot order" in body
    assert (
        "yoke qa plan run --item PREFIX-N --transition TRANSITION "
        "--base-url https://preview.example"
    ) in body
    assert "server-authorized execution before any local executor runs" in body
    assert "immutable roster, digest, durable cursor" in body
    assert "Waiting runs resume from the same cursor" in body
    assert "completion or abort releases the lease" in body


def test_qa_packet_drops_retired_browser_execution_teaching() -> None:
    body = sac.render_topic_packet("qa")
    for retired in (
        "browser_smoke",
        "browser_diff",
        "yoke qa browser run",
        "--executor-type browser_substrate",
        '--success-policy \'{"steps"',
    ):
        assert retired not in body


def test_qa_packet_replaces_run_add_trailing_parenthetical() -> None:
    body = sac.render_topic_packet("qa")
    assert (
        "CLI adapter `qa run-add` accepts `--raw-result-file PATH` for "
        "multi-line evidence blobs."
    ) not in body
    assert "yoke qa run get --run-id <id>" in body
    assert "Registered read qa.run.get" in body
    assert "no registered id" not in body
