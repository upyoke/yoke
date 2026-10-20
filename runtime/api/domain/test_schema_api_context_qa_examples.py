"""QA schema examples in rendered agent packets."""

from __future__ import annotations

import re

import pytest

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.schema_api_context_commands_qa import QA_COMMANDS
from yoke_core.domain.schema_api_context_render import PACKET_DETAIL_FULL


def test_main_agent_packet_teaches_qa_requirement_run_columns() -> None:
    body = sac.render_topic_packet("qa", role="main_agent", detail=PACKET_DETAIL_FULL)
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
    body = sac.render_topic_packet("qa", detail=PACKET_DETAIL_FULL)
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
        "runner_id",
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
    body = sac.render_topic_packet("qa", detail=PACKET_DETAIL_FULL)
    for column in (
        "score",
        "confidence",
        "duration_ms",
        "started_at",
        "completed_at",
        "execution_status",
    ):
        assert column in body, f"qa_runs column {column!r} missing from qa packet"
    assert (
        "execution_status` is capture-stage bookkeeping for browser and "
        "agent-mission runs"
    ) in body


def test_qa_packet_carries_canonical_unsatisfied_verification_select() -> None:
    body = sac.render_topic_packet("qa", detail=PACKET_DETAIL_FULL)
    assert "Canonical unsatisfied-verification SELECT" in body
    assert "FROM qa_requirements qr WHERE qr.item_id = %s" in body
    assert "qr.qa_phase = 'verification' AND qr.waived_at IS NULL" in body
    assert "has_current_passing_run" in body
    assert "EXISTS(verdict=pass) is not current" in body


def test_qa_packet_carries_requirement_add_ac_verification_example() -> None:
    body = sac.render_topic_packet("qa", detail=PACKET_DETAIL_FULL)
    assert "Add a QA requirement — ac_verification variant" in body
    assert (
        "yoke qa requirement add "
        "--item PREFIX-N --qa-kind ac_verification --qa-phase verification "
        "--blocking-mode blocking --requirement-source ac_derived "
        "--workflow-transition STAGE"
    ) in body
    assert "`--workflow-transition` is required" in body
    assert "precedes a qa_verification gate" in body
    assert "the accepted form is `all-pass`" in body
    assert "every row must include `workflow_transition_id`" in body
    # The same command attaches a case to a release, so the packet teaches
    # that form rather than sending an agent to an operator-debug CLI.
    assert "--deployment-run run-YYYYMMDD-NNN" in body
    assert "A run-attached case requires `--method-id`" in body
    assert "authorized by the run's project scope" in body
    assert (
        "yoke workflow-item epic-task review-seed --epic PREFIX-N --task-num K"
    ) in body


@pytest.mark.parametrize("role", ("engineer_agent", "tester_agent"))
def test_qa_runner_packets_require_transition_bound_creation(role: str) -> None:
    body = sac.render_topic_packet("qa", role=role, detail=PACKET_DETAIL_FULL)
    assert (
        "yoke qa requirement add "
        "--item PREFIX-N --qa-kind ac_verification --qa-phase verification "
        "--blocking-mode blocking --requirement-source ac_derived "
        "--workflow-transition STAGE"
    ) in body
    assert "every row must include `workflow_transition_id`" in body
    assert (
        "yoke workflow-item epic-task review-seed --epic PREFIX-N --task-num K"
    ) in body


def test_qa_packet_carries_plan_case_materialization_example() -> None:
    body = sac.render_topic_packet("qa", detail=PACKET_DETAIL_FULL)
    assert "Materialize attached QA plan cases for a transition" in body
    assert (
        "yoke qa plan materialize --item PREFIX-N --transition STAGE"
    ) in body
    assert (
        "yoke qa item-plan retract --item PREFIX-N --project P "
        "--plan-id N --transition T --reason TEXT"
    ) in body
    for field in (
        "method_id",
        "expected_outcome",
        "method_config snapshot",
    ):
        assert field in body


def test_qa_packet_carries_run_add_agent_ac_verification_example() -> None:
    body = sac.render_topic_packet("qa", detail=PACKET_DETAIL_FULL)
    assert "Add a QA run verdict — agent × ac_verification (inline raw_result)" in body
    assert (
        "yoke qa run add "
        "--requirement-id R --performed-by agent "
        "--qa-kind ac_verification --verdict pass "
    ) in body
    assert "`--qa-kind` defaults to the requirement's kind" in body


def test_qa_packet_carries_per_requirement_browser_case_run_example() -> None:
    body = sac.render_topic_packet("qa", detail=PACKET_DETAIL_FULL)
    assert "Run one QA case" in body
    assert (
        "yoke qa case run --requirement-id R "
        "--base-url https://preview.example "
        "--expected-branch BRANCH --expected-sha SHA"
    ) in body
    assert "qa.case_execution.begin" in body
    assert "executes only requirement R" in body
    assert "browser-check decides automatically" in body
    assert "browser-inspection attaches evidence before an undetermined verdict" in body
    assert "`yoke qa run record-verdict" in body
    assert "halts the item and creates an owner/operator review request" in body
    assert "records blocked_on_precondition instead" in body
    assert "A Command case exports `--base-url` as `BASE_URL`" in body
    assert "`YOKE_PYTHON`" in body
    assert "`method_config.command`" in body
    assert "`/bin/sh -c`" in body
    assert "yoke claims coordination-claim release --claim-id N" in body


def test_qa_packet_carries_ordered_plan_run_example() -> None:
    body = sac.render_topic_packet("qa", detail=PACKET_DETAIL_FULL)
    assert "Execute immutable QA plans for an item, deployment, or project" in body
    assert (
        "yoke qa plan run --item PREFIX-N --transition TRANSITION "
        "--base-url https://preview.example"
    ) in body
    assert "server-authorized execution before any local runner runs" in body
    assert "immutable roster, digest, durable cursor" in body
    assert "Waiting runs resume from the same cursor" in body
    assert "completion or abort releases the lease" in body
    assert "yoke qa plan run --plan PLAN --project P" in body
    assert "it never credits an item or deployment gate" in body


def test_qa_packet_drops_retired_browser_execution_teaching() -> None:
    body = sac.render_topic_packet("qa", detail=PACKET_DETAIL_FULL)
    for retired in (
        "browser_smoke",
        "browser_diff",
        "yoke qa browser run",
        "--performed-by browser_substrate",
        '--success-policy \'{"steps"',
    ):
        assert retired not in body


def test_qa_packet_replaces_run_add_trailing_parenthetical() -> None:
    body = sac.render_topic_packet("qa", detail=PACKET_DETAIL_FULL)
    assert (
        "CLI adapter `qa run-add` accepts `--raw-result-file PATH` for "
        "multi-line evidence blobs."
    ) not in body
    assert "yoke qa run get --run-id <id>" in body
    assert "Registered read qa.run.get" in body
    assert "no registered id" not in body


_TRANSITION = re.compile(
    r"(?:--workflow-transition|--transition|--to)\s+([A-Za-z0-9_{}-]+)"
    r'|"workflow_transition_id":\s*"([^"]+)"'
)


def _stages_every_qa_workflow_has() -> set[str]:
    """Stage ids shared by every current workflow that carries a QA gate.

    A recipe naming a concrete stage must work whichever workflow pins the
    reader's item; any other stage is taught as a placeholder.
    """
    latest: dict[str, dict] = {}
    for generation in canon_generations():
        latest[generation.workflow_id] = generation.definition
    qa_workflows = [
        definition
        for definition in latest.values()
        if any(
            gate.get("id") == "qa_verification"
            for stage in definition["stages"]
            for gate in stage.get("gates", [])
        )
    ]
    assert qa_workflows
    return set.intersection(
        *({stage["id"] for stage in definition["stages"]} for definition in qa_workflows)
    )


def _qa_command_text() -> str:
    return "\n".join(
        f"{command['recipe']}\n{command.get('notes', '')}" for command in QA_COMMANDS
    )


def test_qa_packet_never_teaches_a_python_module_entrypoint() -> None:
    assert "python3 -m" not in _qa_command_text()


def test_qa_packet_transitions_name_live_workflow_stages() -> None:
    stages = _stages_every_qa_workflow_has()
    assert "reviewing-implementation" in stages
    assert "reviewed-implementation" not in stages
    unknown = sorted(
        name
        for match in _TRANSITION.finditer(_qa_command_text())
        for name in match.groups()
        if name and not name.isupper() and name not in stages
    )
    assert not unknown, f"QA packet teaches transitions no live workflow has: {unknown}"

