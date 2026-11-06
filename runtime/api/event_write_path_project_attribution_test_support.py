# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import uuid

from pathlib import Path

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS

from yoke_core.api.routes.hooks import HookEvaluateRequest, _emit_route_denial

from yoke_core.domain import emit_event as emit_event_cli

from yoke_core.domain import events_crud

from yoke_core.domain.db_helpers import connect, iso8601_now

from yoke_core.domain.events import emit_event as emit_event_native

from yoke_core.domain.events_writes import cmd_insert

from yoke_core.domain.handlers import events_reads

from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS

from yoke_core.hooks.denial import emit_denial_event

from runtime.api.fixtures.file_test_db import init_test_db

YOKE_ID = SEED_PROJECT_IDS["yoke"]

EXTERNAL_ID = SEED_PROJECT_IDS["externalwebapp"]

PROVIDERS = {
    "claude-code": "anthropic",
    "codex": "openai",
    "cursor": "cursor",
}

@pytest.fixture
def events_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path

def _seed_session(db_path: str, session_id: str, *, executor: str, project_id: int) -> None:
    now = iso8601_now()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id, executor, provider, model, workspace, project_id, "
            "offered_at, last_heartbeat) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                session_id,
                executor,
                PROVIDERS[executor],
                "test-model",
                "/tmp/workspace",
                project_id,
                now,
                now,
            ),
        )
        conn.commit()

def _project_id(db_path: str, event_id: str) -> int | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT project_id FROM events WHERE event_id = %s",
            (event_id,),
        ).fetchone()
    return None if row is None or row[0] is None else int(row[0])
