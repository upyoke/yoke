# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import base64

import io

import json

import urllib.error

from pathlib import Path

from unittest.mock import patch

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement

from runtime.api.fixtures.pg_testdb import test_database

from runtime.api.qa_artifact_read_test_support import artifact_read_request

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain import qa_artifact_broker as broker

from yoke_core.domain.handlers.qa_artifact_add import handle_qa_artifact_add

from yoke_core.domain.handlers.qa_artifact_presign import handle_qa_artifact_presign

from yoke_core.domain.handlers.qa_artifact_read import handle_qa_artifact_read

from yoke_core.domain.handlers.qa_browser_writes import handle_qa_run_add


def _broker_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    token = tmp_path / "broker.token"
    token.write_text("tenant-service-token\n", encoding="utf-8")
    values = {
        broker.BUCKET_ENV: "yoke-prod-artifacts",
        broker.PREFIX_ENV: "tenants/7",
        broker.BROKER_URL_ENV: "http://host.docker.internal:8601/tenant/qa-artifacts/presign",
        broker.TOKEN_FILE_ENV: str(token),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return token


def _request(function: str, requirement_id: int, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload=payload,
    )


def _seed_run(conn) -> int:
    insert_item(conn, id=42, title="T", status="reviewing-implementation")
    insert_qa_requirement(
        conn,
        id=10,
        item_id=42,
        qa_kind="plan_case",
        qa_phase="verification",
        blocking_mode="blocking",
        success_policy="{}",
        method_id="browser-check",
    )
    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        outcome = handle_qa_run_add(
            _request("qa.run.add", 10, {"performed_by": "browser_substrate"})
        )
    assert outcome.primary_success, outcome.error
    return int(outcome.result_payload["qa_run_id"])


def _signed(operation: str, run_id: int, filename: str) -> broker.BrokerPresign:
    method = "PUT" if operation == "put" else "GET"
    return broker.BrokerPresign(
        url=f"https://s3.example/{operation}",
        method=method,
        bucket="yoke-prod-artifacts",
        key=f"tenants/7/qa-artifacts/yoke/42/{run_id}/{filename}",
        expires_in=900,
    )
