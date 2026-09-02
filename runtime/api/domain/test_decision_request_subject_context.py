"""Gate decision requests refuse payloads that omit decision facts."""

from __future__ import annotations

from copy import deepcopy

import pytest

from runtime.api.domain.decision_request_test_support import (
    decision_request_connection,
)
from yoke_core.domain.decision_request_contract import (
    DEPLOYMENT_STAGE_APPROVAL,
    LIFECYCLE_TRANSITION_APPROVAL,
    QA_NEEDS_REVIEW,
)
from yoke_core.domain.decision_request_subject_context import (
    APPROVAL_SOURCE_WORKFLOW_DEFAULT,
    DecisionRequestSubjectContextError,
    SUBJECT_CONTEXT_INVALID,
    validate_subject_context,
)
from yoke_core.domain.decision_requests import RoleAuthority, create_decision_request


SUBJECTS = {
    QA_NEEDS_REVIEW: (
        "qa_requirement",
        "71",
        {
            "requirement_id": 71,
            "run_id": 72,
            "expected_outcome": "The saved state is visible.",
            "verdict_reason": "The screenshot is ambiguous.",
            "artifacts": [
                {"artifact_id": 73, "artifact_type": "screenshot"},
            ],
            "artifact_count": 1,
            "evidence_state": "attached",
            "evidence_summary": "1 attached artifact(s): screenshot",
        },
    ),
    LIFECYCLE_TRANSITION_APPROVAL: (
        "item_transition",
        "74:done",
        {
            "item_id": 74,
            "item_ref": "YOK-74",
            "item_title": "Ship the complete change",
            "from_stage": "reviewing-implementation",
            "to_stage": "done",
            "workflow_id": "issue",
            "workflow_version_id": 7,
            "branch_changes": {
                "branch": "YOK-74",
                "commit_sha": "a" * 40,
                "touched_files": ["src/decision.py"],
                "summary": "Added the decision contract.",
            },
            "approval_source": {
                "kind": APPROVAL_SOURCE_WORKFLOW_DEFAULT,
                "entry": "approval_defaults.done",
            },
        },
    ),
    DEPLOYMENT_STAGE_APPROVAL: (
        "deployment_stage",
        "run-75:production",
        {
            "run_id": "run-75",
            "flow": {"id": "release", "name": "Release"},
            "stage": "production",
            "batch": {
                "item_count": 1,
                "items": [
                    {"item_id": 75, "item_ref": "YOK-75", "title": "Release"},
                ],
            },
            "shipping": {
                "release_lineage": "b" * 40,
                "target_environment": "prod",
                "summary": "Release bbbbbbbbbbbb to prod.",
            },
        },
    ),
}


@pytest.mark.parametrize("kind", tuple(SUBJECTS))
def test_creation_rejects_gate_context_without_required_facts(kind):
    subject_type, subject_key, complete = SUBJECTS[kind]
    context = deepcopy(complete)
    context.pop(next(iter(context)))
    with decision_request_connection() as conn:
        with pytest.raises(
            DecisionRequestSubjectContextError,
            match=SUBJECT_CONTEXT_INVALID,
        ):
            create_decision_request(
                conn,
                kind=kind,
                subject_type=subject_type,
                subject_key=subject_key,
                project_id=10,
                role_authorities=[RoleAuthority("project", 10, "owner")],
                subject_context=context,
            )
        assert conn.execute("SELECT COUNT(*) FROM decision_requests").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("kind", "path", "replacement"),
    (
        (QA_NEEDS_REVIEW, ("artifact_count",), 2),
        (LIFECYCLE_TRANSITION_APPROVAL, ("approval_source", "kind"), "unknown"),
        (DEPLOYMENT_STAGE_APPROVAL, ("batch", "item_count"), 2),
    ),
)
def test_contract_rejects_contradictory_gate_facts(kind, path, replacement):
    context = deepcopy(SUBJECTS[kind][2])
    target = context
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    with pytest.raises(
        DecisionRequestSubjectContextError, match=SUBJECT_CONTEXT_INVALID
    ):
        validate_subject_context(kind, context)
