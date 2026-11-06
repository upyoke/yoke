# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import unittest

from unittest.mock import patch

from yoke_core.domain.handlers import qa_browser, qa_browser_writes

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement

from runtime.api.fixtures.pg_testdb import test_database


def _request(function_id: str, target: TargetRef, payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=target,
        payload=payload or {},
    )


def _seed_browser_requirement(
    conn, *, req_id: int = 10, item_id: int = 42, qa_kind: str = "plan_case"
) -> None:
    insert_item(conn, id=item_id, title="T", status="reviewing-implementation")
    insert_qa_requirement(
        conn,
        id=req_id,
        item_id=item_id,
        qa_kind=qa_kind,
        qa_phase="verification",
        blocking_mode="blocking",
        success_policy='{"id":"all-pass","params":{}}',
    )
    conn.execute(
        "UPDATE qa_requirements SET method_id='browser-check', "
        "instructions=%s, expected_outcome=%s, method_config=%s "
        "WHERE id=%s",
        (
            "Open the page and assert its ready state.",
            "The page is ready.",
            '{"base_url":"http://localhost:9",'
            '"steps":[{"action":"navigate","route":"/"}]}',
            req_id,
        ),
    )
    conn.commit()
