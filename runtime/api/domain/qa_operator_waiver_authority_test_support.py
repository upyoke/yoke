# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver

from runtime.api.domain.steering_claim_test_support import (
    seed_session,
    seed_strategy_doc,
)

from yoke_core.domain.db_helpers import instant_parameter, utc_now

from yoke_contracts.timestamps import parse_instant

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    seed_member_qa_case,
)

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject

from yoke_core.domain.deployment_run_driver_attachment import (
    PHASE_EXECUTING,
    attach_driver,
)

from yoke_core.domain.handlers.__init_register__ import register_all_handlers

from yoke_core.domain.handlers.qa_requirement_waive import handle_qa_requirement_waive

from yoke_core.domain.sessions_lifecycle_claim import claim_work

from yoke_core.domain.steering_claims import acquire as acquire_seat

from yoke_core.domain.yoke_function_dispatch_claims import verify_claim

from yoke_core.domain.yoke_function_registry import lookup

MEMBER = 9801

RUN_ID = "run-member-waiver"

RECORDER = "waiver-recorder"

WORKER = "member-worker"


class _BorrowedConnection:
    """Let production helpers share the test connection without closing it."""

    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def close(self):
        pass


@pytest.fixture
def waiver_world(test_db):
    requirement_id = seed_member_qa_case(test_db, run_id=RUN_ID, member_item_id=MEMBER)
    test_db.execute("UPDATE items SET status='release' WHERE id=%s", (MEMBER,))
    test_db.commit()
    seed_session(test_db, RECORDER, 1)
    seed_session(test_db, WORKER, 1)
    claim = claim_work(test_db, session_id=WORKER, item_id=str(MEMBER))
    with patch(
        "yoke_core.domain.db_helpers.connect",
        side_effect=lambda *a, **k: _BorrowedConnection(test_db),
    ):
        yield test_db, requirement_id, claim


RATIONALE = "operator accepted the release without this case"


def _request(requirement_id, *, source="operator", function="qa.requirement.waive"):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="2", session_id=RECORDER),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload={"rationale": RATIONALE, "source": source, "force": True},
    )


def _drive(conn, session_id, *, now=None):
    """Attach *session_id* as the run's driver; an old *now* leaves it stale."""
    release_seeded_driver(conn, RUN_ID)
    attach_driver(
        conn, RUN_ID, session_id=session_id, pid=4242, phase=PHASE_EXECUTING, now=now
    )
    conn.commit()
