"""Effective path-survey workflow policy coverage."""

from __future__ import annotations

import pytest

from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_PREFERRED_VERSION,
    builtin_workflow_definition,
)
from yoke_core.domain.item_posture_validation import (
    ItemPostureError,
    validate_item_posture,
)
from yoke_core.domain.workflow_effective_policies import (
    resolve_effective_workflow_policies,
)
from yoke_core.domain.workflow_policy_defaults import (
    publish_workflow_policy_defaults,
)
from yoke_core.domain.workflow_registry import get_workflow_version
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


def test_direct_workflows_default_path_survey_on_beside_optional_claims():
    definitions = {
        workflow_id: builtin_workflow_definition(workflow_id)["definition"]
        for workflow_id in ("blitz", "dash")
    }

    assert all(
        definition["policies"]["path_survey"] == "required"
        for definition in definitions.values()
    )
    assert all(
        definition["policies"]["path_claims"] == "optional"
        for definition in definitions.values()
    )
    assert all(
        "path_survey" in definition["policies"]["item_posture_allowlist"]
        for definition in definitions.values()
    )


@pytest.mark.parametrize(
    ("posture", "path_survey", "path_claims"),
    [
        ({}, "required", "optional"),
        ({"path_survey": True}, "required", "optional"),
        ({"path_claims": True}, "required", "required"),
        ({"path_survey": True, "path_claims": True}, "required", "required"),
    ],
)
def test_effective_survey_and_claim_axes_are_independent(
    posture, path_survey, path_claims,
):
    effective = resolve_effective_workflow_policies(
        builtin_workflow_runtime("dash"),
        posture,
    )

    assert effective.path_survey == path_survey
    assert effective.path_claims == path_claims


def test_optional_path_survey_can_be_tightened_at_item_creation():
    definition = builtin_workflow_definition("dash")["definition"]
    definition["policies"]["path_survey"] = "optional"

    assert validate_item_posture(
        None,
        definition=definition,
        project_id=1,
        posture={"path_survey": True},
    ) == {"path_survey": True}

    definition["policies"]["path_survey"] = "required"
    with pytest.raises(ItemPostureError, match="only tightens"):
        validate_item_posture(
            None,
            definition=definition,
            project_id=1,
            posture={"path_survey": True},
        )


def test_path_survey_default_publishes_without_changing_path_claims(test_db):
    published = publish_workflow_policy_defaults(
        test_db,
        workflow_id="dash",
        expected_current_version=BUILTIN_WORKFLOW_PREFERRED_VERSION,
        path_survey_default=False,
        published_by_actor_id=1,
    )

    assert published["path_survey_default"] is False
    version = get_workflow_version(
        test_db,
        workflow_id="dash",
        version=BUILTIN_WORKFLOW_PREFERRED_VERSION + 1,
    )
    policies = version["definition"]["policies"]
    assert policies["path_survey"] == "optional"
    assert policies["path_claims"] == "optional"
