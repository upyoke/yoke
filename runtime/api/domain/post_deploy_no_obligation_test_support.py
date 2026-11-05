# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from contextlib import contextmanager

from unittest.mock import patch

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

from yoke_core.domain.deployment_qa_stage_materialization import (
    QaCasesNotSelectedError,
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_stage_outcome import OUTCOME_DISCHARGED

from yoke_core.domain.handlers import qa_post_deploy_record_no_obligation as record

from yoke_core.domain.post_deploy_verification_answer import (
    NO_OBLIGATION,
    NO_OBLIGATION_QA_KIND,
    UNANSWERED,
    answer_for_item,
    classify,
)

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


@contextmanager
def _handler_uses(conn):
    class _Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)

        def close(self):
            return None

    with patch("yoke_core.domain.db_helpers.connect", return_value=_Borrowed()):
        yield


def _seed_item(conn, *, item_id: int, sequence: int):
    from runtime.api.fixtures.backlog_inserts import insert_item

    insert_item(
        conn,
        id=item_id,
        project_sequence=sequence,
        workflow_id="dash",
        status="release",
    )
    conn.commit()


def _no_obligation_row(conn, item_id: int, reason: str) -> int:
    """The artifact ``record-no-obligation`` writes, as the stage will read it."""
    requirement_id = int(
        conn.execute(
            "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,blocking_mode,"
            "requirement_source,instructions,workflow_transition_id,created_at) "
            "VALUES (%s,%s,'post_deploy','non_blocking','explicit',%s,'release',"
            "'2026-09-20T00:00:00Z') RETURNING id",
            (int(item_id), NO_OBLIGATION_QA_KIND, reason),
        ).fetchone()[0]
    )
    conn.commit()
    return requirement_id


def _record(item_id: int, reason: str) -> object:
    return record.handle_qa_post_deploy_record_no_obligation(
        FunctionCallRequest(
            function="qa.post_deploy.record_no_obligation",
            actor=ActorContext(actor_id="op", session_id="s-1"),
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={"reason": reason},
        )
    )
