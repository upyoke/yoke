"""A case naming another environment's endpoint is refused before it runs."""

from __future__ import annotations

import pytest

from yoke_contracts.api_urls import DISTRIBUTION_PROD_URL, DISTRIBUTION_STAGE_URL
from yoke_core.domain import (
    item_ref_render,
    qa_execution_environment_target as environment_target,
    qa_plan_attachments,
    qa_plan_case_definition,
    qa_plan_project_defaults,
)
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError,
    require_requirement_target,
)
from yoke_core.domain.qa_plan_case_targets import (
    require_materialized_case_target,
    validate_case_targets,
)
from yoke_core.domain.qa_plan_management import QaPlanError
from runtime.api.domain.qa_release_channel_target_test_support import _target

PLAN = {"id": 7, "project_id": 1, "target_environment_id": 3}
STAGE_URL = f"{DISTRIBUTION_STAGE_URL}/install.sh"


def _case(url: str, **extra) -> dict:
    return {
        "case_key": "install-probe",
        "method_id": "command",
        "instructions": f"Fetch {url} and check it answers.",
        "expected_outcome": "It answers.",
        "method_config": {},
        "entry_surface": None,
        "target_envs": [],
        **extra,
    }


@pytest.fixture
def production_default(monkeypatch):
    calls = []

    def resolve(conn, *, plan_id, require_runtime_match=True, allow_unbound=False):
        calls.append(plan_id)
        return _target("production")

    monkeypatch.setattr(environment_target, "resolve_plan_execution_target", resolve)
    return calls


def test_case_without_target_envs_is_checked_against_plan_default(production_default):
    with pytest.raises(QaPlanError) as refused:
        validate_case_targets(None, plan=PLAN, case=_case(STAGE_URL))
    message = str(refused.value)
    assert "case 'install-probe' of QA plan 7: case_target_mismatch" in message
    assert "api.stage.upyoke.com" in message
    assert "'production'" in message and "yoke qa plan cases" in message
    assert production_default == [7]


def test_case_naming_its_own_target_endpoint_passes(production_default):
    validate_case_targets(
        None, plan=PLAN, case=_case(f"{DISTRIBUTION_PROD_URL}/install.sh")
    )


def test_unbound_plan_has_no_default_endpoints_to_check(production_default):
    plan = {**PLAN, "target_environment_id": None}
    validate_case_targets(None, plan=plan, case=_case(STAGE_URL))
    assert production_default == []


@pytest.fixture
def stored_stage_case(monkeypatch, production_default):
    monkeypatch.setattr(
        qa_plan_case_definition, "plan_cases", lambda conn, plan_id: [_case(STAGE_URL)]
    )
    for module in (qa_plan_attachments, qa_plan_project_defaults):
        monkeypatch.setattr(module, "_plan_row", lambda conn, plan_id: dict(PLAN))
        monkeypatch.setattr(module, "require_plan_cases", lambda conn, plan_id: None)


def test_attaching_to_an_item_refuses_a_wrong_target_case(stored_stage_case):
    with pytest.raises(QaPlanError, match="case_target_mismatch"):
        qa_plan_attachments.attach_plan_to_item(
            None, plan_id=7, item_id=11, transition_id="done", qa_phase="post_deploy"
        )


def test_project_default_attach_refuses_a_wrong_target_case(stored_stage_case):
    with pytest.raises(QaPlanError, match="case_target_mismatch"):
        qa_plan_project_defaults.set_project_default(
            None, plan_id=7, workflow_id="dash", transition_id="done"
        )


def test_execution_refusal_names_requirement_and_item():
    context = {
        **_case(STAGE_URL),
        "requirement_id": 68678,
        "public_ref": "PLAT-436",
        "deployment_run_id": "run-1",
    }
    with pytest.raises(QaExecutionTargetError) as refused:
        require_requirement_target(context, _target("production"))
    message = str(refused.value)
    assert message.startswith(
        "QA requirement 68678 (case 'install-probe', item PLAT-436, "
        "deployment run run-1): mixed-environment QA endpoint"
    )
    assert "yoke qa requirement update" in message


def test_materialization_refusal_names_plan_case_and_item(monkeypatch):
    monkeypatch.setattr(
        item_ref_render, "render_item_refs", lambda conn, ids: {11: "PLAT-438"}
    )
    with pytest.raises(QaExecutionTargetError) as refused:
        require_materialized_case_target(
            None,
            case=_case(STAGE_URL),
            definition={"plan_id": 7, "method_config": "{}"},
            target=_target("production"),
            owner={"item_id": 11, "deployment_run_id": None},
        )
    assert str(refused.value).startswith(
        "QA plan 7 case 'install-probe', item PLAT-438: mixed-environment"
    )
