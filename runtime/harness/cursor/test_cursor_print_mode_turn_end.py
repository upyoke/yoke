"""Cursor print mode ends its turn on ``sessionEnd``, never ``stop``.

A live ``cursor-agent --print --output-format stream-json`` probe
(2026.10.01-e373342) fired sessionStart, afterAgentThought, the tool hooks,
and sessionEnd — no stop, afterAgentResponse, or beforeSubmitPrompt. The
payload and transcript below are that probe's recorded wire shape, so the
turn-end duties the Stop chain owns must run on this SessionEnd instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.turn_end_promised_work_test_support import _Conn
from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
from yoke_contracts.session_control import (
    capability_for_surface,
    turn_end_events,
)
from yoke_contracts.turn_end_evidence import PAYLOAD_KEY
from yoke_core.domain import turn_end_promised_work_gate as gate
from yoke_core.hooks.types import HookContext, Outcome
from yoke_harness.hooks import local_subset
from yoke_harness.hooks.deadline import start_hook_deadline


CONVERSATION = "72e9d9b5-4f5a-4b2d-8429-6dc8dbe3b4e9"
TRANSCRIPT_LINES = (
    {
        "role": "user",
        "message": {"content": [{"type": "text", "text": "Run echo probe."}]},
    },
    {
        "role": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "I'll run `echo probe`."},
                {
                    "type": "tool_use",
                    "name": "Shell",
                    "input": {"command": "echo probe"},
                },
            ]
        },
    },
    {"role": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
    {"type": "turn_ended", "status": "success"},
)


def _session_end_payload(transcript: Path) -> dict:
    return {
        "conversation_id": CONVERSATION,
        "generation_id": CONVERSATION,
        "model": "grok-4.7-high",
        "reason": "completed",
        "duration_ms": 4261,
        "is_background_agent": False,
        "final_status": "completed",
        "session_id": CONVERSATION,
        "hook_event_name": "sessionEnd",
        "cursor_version": "2026.10.01-e373342",
        "workspace_roots": ["/tmp/cursor-probe"],
        "transcript_path": str(transcript),
    }


@pytest.fixture()
def transcript(tmp_path: Path) -> Path:
    path = tmp_path / f"{CONVERSATION}.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in TRANSCRIPT_LINES))
    return path


def _ctx(payload: dict, *, family: str = "cursor") -> HookContext:
    return HookContext(
        event_name="SessionEnd",
        executor_family=family,
        executor_surface=family,
        payload=payload,
        session_id=CONVERSATION,
    )


def _patch_db(monkeypatch, *, continuation: bool = False) -> list[dict]:
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: _Conn())
    monkeypatch.setattr(
        gate, "_live_claim", lambda conn, sid: {"item_id": 7, "status": "implementing"}
    )
    monkeypatch.setattr(gate, "session_was_relay_launched", lambda conn, sid: True)
    monkeypatch.setattr(gate, "session_parked", lambda conn, sid: False)
    monkeypatch.setattr(
        gate,
        "stop_denial_continuation_supported",
        lambda *args, **kwargs: continuation,
    )
    emitted: list[dict] = []
    monkeypatch.setattr(gate, "_emit_deferred", lambda **kw: emitted.append(kw))
    return emitted


def test_manifest_declares_cursor_cli_turn_end_on_session_end() -> None:
    assert capability_for_surface("cursor-cli").turn_end_event == "SessionEnd"
    assert capability_for_surface("cursor-desktop").turn_end_event == "Stop"
    assert turn_end_events("cursor") == {"Stop", "SessionEnd"}
    assert turn_end_events("claude") == {"Stop"}
    assert turn_end_events("codex") == {"Stop"}


def test_session_end_chain_runs_the_gate_before_lifecycle_dispatch() -> None:
    chain = ordered_pipeline_for("SessionEnd")
    gate_at = chain.index("yoke_core.domain.turn_end_promised_work_gate")
    assert gate_at < chain.index("yoke_core.hooks.session_dispatch")


def test_print_mode_session_end_records_the_turn_end_deferral(
    monkeypatch, transcript: Path
) -> None:
    emitted = _patch_db(monkeypatch)
    decision = gate.evaluate(_ctx(_session_end_payload(transcript)))
    assert decision.outcome is Outcome.ALLOW
    assert [e["reason"] for e in emitted] == [gate.REASON_CONTINUATION_UNSUPPORTED]
    assert emitted[0]["item_id"] == 7


def test_session_end_never_denies_even_where_stop_could_continue(
    monkeypatch, transcript: Path
) -> None:
    emitted = _patch_db(monkeypatch, continuation=True)
    decision = gate.evaluate(_ctx(_session_end_payload(transcript)))
    assert decision.outcome is Outcome.ALLOW
    assert [e["reason"] for e in emitted] == [gate.REASON_CONTINUATION_UNSUPPORTED]


def test_session_end_on_a_stop_surface_is_untouched(
    monkeypatch, transcript: Path
) -> None:
    emitted = _patch_db(monkeypatch)
    decision = gate.evaluate(_ctx(_session_end_payload(transcript), family="claude"))
    assert decision.outcome is Outcome.NOOP
    assert emitted == []


def test_relay_client_attaches_turn_end_evidence_on_cursor_session_end(
    transcript: Path,
) -> None:
    result = local_subset.evaluate_local_subset(
        "SessionEnd",
        json.dumps(_session_end_payload(transcript)),
        "cursor",
        None,
        start_hook_deadline(),
        lint_config_snapshot={},
    )
    evidence = (result.payload_extra or {}).get(PAYLOAD_KEY)
    assert evidence == {"available": True, "present": True, "question": False}
