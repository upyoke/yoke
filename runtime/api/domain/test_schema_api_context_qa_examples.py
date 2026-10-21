"""QA schema examples in rendered agent packets."""

from __future__ import annotations

import re

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.schema_api_context_commands_qa import QA_COMMANDS
from yoke_core.domain.schema_api_context_render import PACKET_DETAIL_FULL


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
