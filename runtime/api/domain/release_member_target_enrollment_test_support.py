# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import pytest

from runtime.api.domain.dash_post_deploy_done_consumption_test_support import (
    _accept_member_qa,
    _bind_original,
    _transition_done,
)

from runtime.api.domain.dash_post_deploy_review_isolation_test_support import (
    _insert_dash,
)

from runtime.api.domain.deployment_qa_admission_execution_test_support import (
    _seed_selected_requirement_run,
)

from runtime.api.domain.post_deploy_original_pass_needs_admission_test_support import (
    _record_evidence,
)

from runtime.api.fixtures.backlog_inserts import insert_qa_run

from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver

from yoke_core.domain.deployment_item_completion_runs import completion_runs

from yoke_core.domain.gate_satisfier_resolution import record_delivery_evidence_rung

from yoke_core.domain.deployment_member_post_deploy_admission import (
    post_deploy_admission_split,
)

from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_run_member_targeting import (
    covering_holder_pairs,
    needed_member_ids,
)


def _pair(conn, *, item_id):
    _insert_dash(conn, item_id=item_id, status="release")
    sources = {}
    for environment in ("stage", "prod"):
        source = _bind_original(conn, item_id=item_id)
        conn.execute(
            "UPDATE qa_requirements SET target_env=%s WHERE id=%s",
            (environment, source),
        )
        conn.commit()
        _seed_selected_requirement_run(
            conn,
            run_id=f"run-{environment}",
            item_id=item_id,
            requirement_id=source,
            environment=environment,
        )
        conn.execute(
            "UPDATE deployment_flows SET target_tier='persistent',target_environment_id="
            "(SELECT id FROM environments WHERE project_id=1 AND name=%s) WHERE id=%s",
            (environment, f"flow-run-{environment}"),
        )
        conn.execute(
            "UPDATE deployment_runs SET target_tier='persistent',target_environment_id="
            "(SELECT id FROM environments WHERE project_id=1 AND name=%s) WHERE id=%s",
            (environment, f"run-{environment}"),
        )
        sources[environment] = source
    conn.commit()
    return sources
