"""CLI/cmd_insert event writes share the native envelope-aware project resolver."""

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
from yoke_core.domain.events_project_identity import SESSION_SCOPED_EVENT_TYPES
from yoke_core.domain.events_writes import cmd_insert
from yoke_core.domain.handlers import events_reads
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from yoke_core.hooks.denial import emit_denial_event
from runtime.api.fixtures.file_test_db import init_test_db

YOKE_ID = SEED_PROJECT_IDS["yoke"]
EXTERNAL_ID = SEED_PROJECT_IDS["externalwebapp"]
EXTERNAL_SLUG = "externalwebapp"
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


def _query(project: str, session_id: str, event_name: str = "HarnessToolCallDenied"):
    return events_reads.handle_events_query(
        FunctionCallRequest(
            function="events.query.run",
            actor=ActorContext(actor_id="op", session_id="s-caller"),
            target=TargetRef(kind="global"),
            payload={
                "project": project,
                "session_id": session_id,
                "event_name": event_name,
            },
        )
    )


def _write(writer: str, *, event_id: str, session_id: str, event_type: str, project: str, envelope=None, context=None) -> str:
    if writer == "native":
        result = emit_event_native(
            "AttributionProbe",
            event_kind="system",
            event_type=event_type,
            source_type="hook",
            session_id=session_id,
            project=project,
            context=context,
        )
        assert result.ok and result.event_id
        return str(result.event_id)
    if writer == "cli":
        args = [
            "--name", "AttributionProbe",
            "--kind", "system",
            "--type", event_type,
            "--source-type", "hook",
            "--session-id", session_id,
            "--event-id", event_id,
            "--project", project,
        ]
        if context is not None:
            args.extend(["--context", json.dumps(context)])
        assert emit_event_cli.main(args) == 0
        return event_id
    cmd_insert(
        event_id=event_id,
        source_type="hook",
        session_id=session_id,
        event_kind="system",
        event_type=event_type,
        event_name="AttributionProbe",
        project=project,
        envelope=envelope,
        skip_severity=True,
    )
    return event_id


@pytest.mark.parametrize("writer", ["native", "cli", "raw"])
@pytest.mark.parametrize("event_type", sorted(SESSION_SCOPED_EVENT_TYPES))
def test_session_scoped_writers_follow_registered_session_project(
    events_db, writer, event_type
):
    session_id = f"sess-{writer}-{event_type}"
    event_id = f"evt-{uuid.uuid4().hex[:12]}"
    _seed_session(events_db, session_id, executor="cursor", project_id=EXTERNAL_ID)
    envelope = None
    if writer == "raw":
        envelope = json.dumps({"session_id": "other", "event_type": "test", "project": "yoke"})
    written = _write(
        writer,
        event_id=event_id,
        session_id=session_id,
        event_type=event_type,
        project="yoke",
        envelope=envelope,
    )
    assert _project_id(events_db, written) == EXTERNAL_ID


@pytest.mark.parametrize("writer", ["native", "cli", "raw"])
def test_explicit_context_project_outranks_session_and_boundary(events_db, writer):
    session_id = f"sess-ctx-{writer}"
    event_id = f"evt-{uuid.uuid4().hex[:12]}"
    _seed_session(events_db, session_id, executor="codex", project_id=YOKE_ID)
    context = {"project_id": EXTERNAL_ID}
    envelope = None
    if writer == "raw":
        envelope = json.dumps(
            {
                "context": {"detail": {"project_id": EXTERNAL_ID}},
                "session_id": "ignored",
                "project": "yoke",
            }
        )
        context = None
    written = _write(
        writer,
        event_id=event_id,
        session_id=session_id,
        event_type="tool_call",
        project="yoke",
        envelope=envelope,
        context=context,
    )
    assert _project_id(events_db, written) == EXTERNAL_ID


def test_raw_insert_without_envelope_follows_session(events_db):
    session_id = "sess-raw-plain"
    _seed_session(events_db, session_id, executor="claude-code", project_id=EXTERNAL_ID)
    cmd_insert(
        event_id="evt-raw-plain",
        source_type="hook",
        session_id=session_id,
        event_kind="audit",
        event_type="tool_call",
        event_name="HarnessToolCallDenied",
        project="yoke",
        skip_severity=True,
    )
    assert _project_id(events_db, "evt-raw-plain") == EXTERNAL_ID


def test_non_session_event_keeps_boundary_project_despite_session(events_db):
    session_id = "sess-global-mention"
    event_id = "evt-non-session"
    _seed_session(events_db, session_id, executor="claude-code", project_id=EXTERNAL_ID)
    cmd_insert(
        event_id=event_id,
        source_type="system",
        session_id=session_id,
        event_kind="lifecycle",
        event_type="test",
        event_name="NotSessionScoped",
        project="yoke",
        skip_severity=True,
    )
    assert _project_id(events_db, event_id) == YOKE_ID


@pytest.mark.parametrize("session_id", ["", "unknown", "sess-missing"])
def test_unknown_or_sessionless_identity_uses_boundary_project(events_db, session_id):
    event_id = f"evt-unknown-{session_id or 'empty'}"
    cmd_insert(
        event_id=event_id,
        source_type="hook",
        session_id=session_id,
        event_kind="audit",
        event_type="tool_call",
        event_name="HarnessToolCallDenied",
        project="yoke",
        skip_severity=True,
    )
    assert _project_id(events_db, event_id) == YOKE_ID


def test_global_token_indexes_as_null(events_db):
    cmd_insert(
        event_id="evt-global",
        source_type="system",
        session_id="sess-any",
        event_kind="system",
        event_type="test",
        event_name="FleetWide",
        project="global",
        skip_severity=True,
    )
    assert _project_id(events_db, "evt-global") is None


def test_non_object_envelope_json_uses_row_identity(events_db):
    session_id = "sess-malformed"
    _seed_session(events_db, session_id, executor="cursor", project_id=EXTERNAL_ID)
    cmd_insert(
        event_id="evt-malformed",
        source_type="hook",
        session_id=session_id,
        event_kind="audit",
        event_type="tool_call",
        event_name="HarnessToolCallDenied",
        project="yoke",
        envelope="[1, 2]",
        skip_severity=True,
    )
    assert _project_id(events_db, "evt-malformed") == EXTERNAL_ID


@pytest.mark.parametrize("executor", CANONICAL_HARNESS_IDS)
def test_denial_emitter_indexes_external_session_and_query_filters(
    events_db, executor
):
    session_id = f"sess-denial-{executor}"
    _seed_session(events_db, session_id, executor=executor, project_id=EXTERNAL_ID)
    emit_denial_event(
        hook="lint-main-commit",
        tool="Bash",
        check_id="impl_on_main",
        reason="implementation on main",
        session_id=session_id,
        tool_use_id=f"tu-{executor}",
        command_snippet="git commit",
    )
    with connect(events_db) as conn:
        row = conn.execute(
            "SELECT event_id, project_id FROM events "
            "WHERE event_name = 'HarnessToolCallDenied' AND session_id = %s",
            (session_id,),
        ).fetchone()
    assert row is not None
    assert int(row[1]) == EXTERNAL_ID
    listed = events_crud.cmd_list(
        events_db,
        ["--project", EXTERNAL_SLUG, "--event-name", "HarnessToolCallDenied"],
    )
    absent = events_crud.cmd_list(
        events_db,
        ["--project", "yoke", "--event-name", "HarnessToolCallDenied"],
    )
    assert session_id in listed
    assert session_id not in absent
    found = _query(EXTERNAL_SLUG, session_id)
    missing = _query("yoke", session_id)
    assert found.primary_success
    assert missing.primary_success
    assert any(item.get("session_id") == session_id for item in found.result_payload["rows"])
    assert found.result_payload["rows"]
    assert not any(item.get("session_id") == session_id for item in missing.result_payload["rows"])


def test_server_route_denial_shares_emitter_attribution(events_db):
    session_id = "sess-server-route"
    _seed_session(events_db, session_id, executor="cursor", project_id=EXTERNAL_ID)
    _emit_route_denial(
        "conversation_shaped_session",
        "route refusal",
        HookEvaluateRequest(
            event_name="PreToolUse",
            stdin=json.dumps({"session_id": session_id, "tool_use_id": "tu-route"}),
            execution_provenance={"source_sha": "clientsha"},
        ),
    )
    with connect(events_db) as conn:
        row = conn.execute(
            "SELECT project_id FROM events "
            "WHERE event_name = 'HarnessToolCallDenied' AND session_id = %s",
            (session_id,),
        ).fetchone()
    assert row is not None
    assert int(row[0]) == EXTERNAL_ID
