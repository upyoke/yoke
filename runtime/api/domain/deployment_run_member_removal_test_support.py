# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import pytest

from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
    seed_member_qa_case,
)

from runtime.api.fixtures.carried_release_candidate import (
    record_landing_receipt,
    release_repository,
    serve_repository,
)

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    _project,
)

from runtime.api.domain.no_obligation_member_close_out_test_support import (
    _ready_member,
    _no_obligation,
)

from runtime.api.domain.run_success_member_settlement_test_support import (
    _executing_run,
    _claim_held,
)

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from yoke_core.domain.dash_execution import record_dash_evidence

from yoke_core.domain.deployment_run_completion_preconditions import (
    unresolved_blocking_qa,
)

from yoke_core.domain.deployment_run_membership_removals import membership_removals

from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding

from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages

from yoke_core.domain.deployment_runs_crud_mutate import cmd_remove_item, cmd_update

ITEM = 9961

RUN = "run-remove-red"

REASON = "red member will ride the next release"


def _red_member(conn):
    requirement = seed_member_qa_case(conn, run_id=RUN, member_item_id=ITEM)
    conn.execute("UPDATE items SET status='release' WHERE id=%s", (ITEM,))
    conn.commit()
    record_case_verdict(conn, requirement, "fail", evidence=True)
    return requirement


def _still_member(conn):
    return (
        conn.execute(
            "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
            (RUN, ITEM),
        ).fetchone()
        is not None
    )
