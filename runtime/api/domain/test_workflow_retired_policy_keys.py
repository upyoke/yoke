"""A retired policy key stays accepted, and only a retired one does.

Retiring a policy cannot rewrite the immutable rows that already carry it, and
the bounded policy-default publication reads a stored definition, edits one key,
and publishes the result. Refusing the retired key there would break every
operator edit on a universe still sitting on an older generation, so validation
tolerates it -- narrowly.
"""

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
from yoke_core.domain.workflow_policy_defaults import (
    publish_workflow_policy_defaults,
)
from yoke_core.domain.workflow_registry import (
    list_current_workflows,
    publish_workflow_version,
)

RETIRED_KEY = "parallelism"


def _definition(workflow_id: str = "issue", **policies):
    definition = deepcopy(
        builtin_workflow_definition(workflow_id)["definition"]
    )
    definition["policies"].update(policies)
    return definition


def test_the_current_definitions_no_longer_carry_the_retired_key():
    for workflow_id in ("issue", "epic", "blitz", "dash"):
        policies = builtin_workflow_definition(workflow_id)["definition"][
            "policies"
        ]
        assert RETIRED_KEY not in policies


def test_a_definition_carrying_the_retired_key_still_validates():
    """What a universe stored before the retirement must still round-trip."""
    validate_workflow_definition(_definition(**{RETIRED_KEY: "inside_item"}))


def test_any_value_of_the_retired_key_passes_because_nothing_reads_it():
    validate_workflow_definition(
        _definition(**{RETIRED_KEY: "a value no version ever held"})
    )


def test_the_retired_key_is_not_required():
    validate_workflow_definition(_definition())


def test_tolerance_does_not_extend_to_other_unknown_keys():
    """A retired key is grandfathered history; a novel one is a mistake."""
    with pytest.raises(WorkflowDefinitionError, match="unknown="):
        validate_workflow_definition(
            _definition(a_key_no_generation_ever_carried="value")
        )


def test_editing_a_policy_default_on_a_stored_definition_carrying_it_works(
    test_db,
):
    """The incident this tolerance exists to prevent.

    The bounded publication reads the stored definition, edits one declared
    default, and republishes. On a universe whose current row predates the
    retirement, refusing the key would fail that edit with a message about a
    policy the operator never touched.
    """
    # Dash exposes path survey as an operator-editable default; the retired key
    # rides along on the stored row the edit is read from.
    stored = _definition("dash", **{RETIRED_KEY: "none"})
    published = publish_workflow_version(
        test_db, workflow_id="dash", definition=stored,
    )
    current = int(published["version"])

    result = publish_workflow_policy_defaults(
        test_db,
        workflow_id="dash",
        expected_current_version=current,
        path_survey_default=False,
    )

    assert int(result["version"]) == current + 1
    row = next(
        row for row in list_current_workflows(test_db) if row["id"] == "dash"
    )
    assert row["definition"]["policies"]["path_survey"] == "optional"
    # Carried forward untouched: dropping it here would be a second, silent
    # edit alongside the one the operator asked for. Taking a canon update is
    # what clears it.
    assert row["definition"]["policies"][RETIRED_KEY] == "none"
