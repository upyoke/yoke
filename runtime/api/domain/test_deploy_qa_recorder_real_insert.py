"""Drive the REAL ``qa_requirements`` insert path for ``cmd_seed_from_flow``.

The mocked integration tests in ``test_deploy_pipeline_qa_integration`` stub
the flow/run reads and pre-seed the requirement row, so the actual insert —
the only seeder a push-triggered, item-less deploy run exercises — had zero
coverage of the real write. These tests run the insert for real against the
ambient canonical-schema test DB, in-process (no subprocess boundary,
matching the production call path), so a regression in the insert path or
its column shape is caught here instead of in production.

No ``deploy_db`` fixture: that fixture installs an inline minimal schema;
these need the full ``qa_requirements`` shape the canonical schema builds
(method_id, capability_requirements, suite_id, workflow_transition_id, ...),
which the conftest's ambient test DB already provides.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_qa_stage_execution import _seed_run
from yoke_core.domain import deploy_qa_recorder


def _flow_derived_stages() -> list[dict[str, Any]]:
    return [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "distribution-publish",
            "step_runner": "github-actions-workflow",
            "workflow": "yoke-distribution-publish.yml",
            "qa_kind": "distribution_publish",
        },
    ]


def test_seed_from_flow_persists_a_real_requirement_row(test_db):
    run_id = "run-real-insert-distpub-0001"
    _seed_run(test_db, run_id=run_id, stages=_flow_derived_stages(), members=())

    seeded = deploy_qa_recorder.cmd_seed_from_flow(run_id)
    assert seeded == 1

    req_id = deploy_qa_recorder.cmd_get_requirement(run_id, "distribution_publish")
    assert req_id is not None
    assert isinstance(req_id, int)


def test_seed_from_flow_is_idempotent_against_the_real_row(test_db):
    run_id = "run-real-insert-distpub-0002"
    _seed_run(test_db, run_id=run_id, stages=_flow_derived_stages(), members=())

    first = deploy_qa_recorder.cmd_seed_from_flow(run_id)
    second = deploy_qa_recorder.cmd_seed_from_flow(run_id)

    assert first == 1
    assert second == 0  # already seeded, no duplicate insert
