"""A workflow chooses one default overlap-prevention level."""

from __future__ import annotations

from copy import deepcopy

import pytest

from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_definition_validation import (
    WorkflowDefinitionError,
    validate_workflow_definition,
)


def _dash_definition() -> dict:
    return deepcopy(builtin_workflow_definition("dash")["definition"])


@pytest.mark.parametrize("path_claims", ["required", "required_per_task"])
def test_path_survey_and_required_path_claims_are_redundant(
    path_claims: str,
):
    definition = _dash_definition()
    definition["policies"]["path_claims"] = path_claims
    definition["policies"]["path_survey"] = "required"

    with pytest.raises(
        WorkflowDefinitionError,
        match=r"path_survey.*path_claims",
    ):
        validate_workflow_definition(definition)


@pytest.mark.parametrize(
    ("path_survey", "path_claims"),
    [
        ("required", "optional"),
        ("optional", "required"),
        ("optional", "optional"),
    ],
)
def test_each_exclusive_coordination_level_validates(
    path_survey: str,
    path_claims: str,
):
    definition = _dash_definition()
    definition["policies"]["path_survey"] = path_survey
    definition["policies"]["path_claims"] = path_claims

    validate_workflow_definition(definition)
