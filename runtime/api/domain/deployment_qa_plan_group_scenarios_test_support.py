# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from unittest import mock

import pytest

from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    MEMBERS,
    RUN,
    SLUG,
    _attach,
    _pass_group,
    _seed,
)

from runtime.api.domain.deployment_qa_stage_execution_test_support import _plan

from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION

from yoke_core.domain.deployment_qa_plan_credit import plan_credit_misses

from yoke_core.domain.deployment_qa_plan_group_dispatch import (
    gate_plan_groups,
)

from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
)

from yoke_core.domain.deployment_qa_plan_groups import (
    retract_unattached_groups,
    run_groups,
)


def _form(conn):
    created = ensure_groups(conn, RUN, "item-qa")
    conn.commit()
    return created


def _pin_flow(conn, members=MEMBERS):
    conn.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=ANY(%s)",
        (f"flow-{RUN}", list(members)),
    )
    conn.commit()


def _manual_plan(conn, plan_id):
    conn.execute(
        "UPDATE qa_plan_cases SET wake_path='manual', "
        "wake_evidence='a production traffic sample is recorded for this release' "
        "WHERE plan_id=%s",
        (plan_id,),
    )
    conn.commit()


def _dispatch(conn):
    stage = {"name": "item-qa", "scope": "item"}
    return gate_plan_groups(conn, stage, run_id=RUN, project_id=1, item_refs=str)
