"""Served-model persistence through deferred resident hook observations."""

from __future__ import annotations

import json
import time

from runtime.api.fixtures.file_test_db import init_test_db
from yoke_contracts.hook_evaluator_protocol import (
    HOOK_BATCH_MODEL_CONFIRMATIONS_FIELD,
)
from yoke_contracts.session_model_facts import facts_from_mapping
from yoke_core.domain import db_backend
from yoke_core.domain.sessions_lifecycle_registry import register_session
from yoke_core.hooks.observation_batch import persist_observation_batch
from yoke_harness.hooks.identity_model_facts import (
    client_model_facts,
)
from yoke_harness.hook_resident_observations import (
    ObservationQueue,
    PendingObservation,
    _MemoryResponse,
)


SESSION = "claude-print-session"
REQUESTED_MODEL = "claude-opus-5[1m]"
SERVED_MODEL = "claude-opus-5"
NOW = "2026-09-04T14:47:01+00:00"


def _bind_completed_launch(conn, actor_id: int) -> None:
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, body, body_sha256, selector_snapshot, "
        "created_at, expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        ("message-print", actor_id, "Run.", "digest", "{}", NOW, NOW),
    )
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id, requester_actor_id, project_id, requested_surface, "
        "selected_surface, requested_model, message_id, state, "
        "registered_session_id, deadline_at, created_at) "
        "VALUES (%s, %s, 1, 'claude-cli', 'claude-cli', %s, %s, "
        "'succeeded', %s, %s, %s)",
        (
            "launch-print",
            actor_id,
            REQUESTED_MODEL,
            "message-print",
            SESSION,
            NOW,
            NOW,
        ),
    )
    conn.commit()


def test_print_session_attests_on_the_first_hook_after_generation(
    tmp_path, monkeypatch
) -> None:
    transcript = tmp_path / "print-session.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"role": "user"}}) + "\n"
    )
    monkeypatch.setenv("YOKE_MODEL", REQUESTED_MODEL)
    monkeypatch.setattr("yoke_cli.config.machine_config.yoke_home", lambda: tmp_path)
    payload = {
        "session_id": SESSION,
        "identity_stamped": True,
        "transcript_path": str(transcript),
        "cwd": str(tmp_path),
        "tool_name": "Read",
        "tool_input": {"file_path": str(transcript)},
        "tool_use_id": "tool-model",
    }

    with init_test_db(tmp_path):
        conn = db_backend.connect()
        try:
            actor_id = int(
                conn.execute(
                    "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
                ).fetchone()[0]
            )
            initial = client_model_facts("SessionStart", payload, "claude-code")
            assert "model" not in initial
            register_session(
                conn,
                session_id=SESSION,
                executor="claude-code",
                provider="anthropic",
                model_facts=facts_from_mapping(initial),
                execution_lane="DARIUS",
                workspace=str(tmp_path),
                project_id=1,
                entrypoint="claude-cli",
                actor_id=actor_id,
            )
            _bind_completed_launch(conn, actor_id)

            with transcript.open("a") as stream:
                stream.write(
                    json.dumps(
                        {"type": "assistant", "message": {"model": SERVED_MODEL}}
                    )
                    + "\n"
                )
            identity = client_model_facts("PreToolUse", payload, "claude-code")
            assert identity["model"] == SERVED_MODEL

            hook_request = {
                "hook_schema": 1,
                "event_name": "PreToolUse",
                "stdin": json.dumps(payload),
                "executor": "claude-code",
                "entrypoint": "claude-cli",
                "project_id": 1,
                "payload_extra": {},
                **identity,
            }

            def deliver(request, timeout=None):  # noqa: ARG001
                body = json.loads(request.data)
                accepted, confirmations = persist_observation_batch(
                    body["observations"], actor_id=actor_id
                )
                return _MemoryResponse(
                    {
                        "accepted": accepted,
                        HOOK_BATCH_MODEL_CONFIRMATIONS_FIELD: confirmations,
                    },
                    url=request.full_url,
                )

            queue = ObservationQueue(deliver)
            queue.enqueue(
                PendingObservation(
                    observation_id="observation-model",
                    endpoint="https://control.test/v1/hooks/telemetry/batch",
                    authorization="Bearer test",
                    observed_at=NOW,
                    hook_wait_ms=1,
                    hook_request=hook_request,
                    enqueued_at=time.monotonic(),
                )
            )
            queue._flush_once()
            assert queue.pending_count() == 0
            assert queue.close()

            row = conn.execute(
                "SELECT model, requested_model FROM harness_sessions "
                "WHERE session_id = %s",
                (SESSION,),
            ).fetchone()
            assert tuple(row) == (SERVED_MODEL, REQUESTED_MODEL)
            bound = conn.execute(
                "SELECT registered_session_id FROM session_launches "
                "WHERE launch_id = 'launch-print'"
            ).fetchone()
            assert bound[0] == SESSION
            assert (tmp_path / "relay-model-shipped" / SESSION).exists()
        finally:
            conn.close()
