"""Cursor conversation-map bind-then-handoff for ACP launches."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.cursor_session_map import record_conversation_session
from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_harness.session_relay_cursor import CursorNativeResult, build_cursor_adapter
from yoke_harness.session_relay_cursor_identity import (
    ACP_SESSION_PARSE_EXPECTATION,
    CURSOR_IDENTITY_LOOKUP_ATTEMPTS,
    bind_launch_session,
    conversation_map_lookup,
    resolve_conversation_session,
    session_id_from_native_payload,
)
from yoke_harness.session_relay_runtime import RelayExecutionContext


CONVERSATION_ID = "11111111-1111-4111-8111-111111111111"
MAPPED_SESSION_ID = "22222222-2222-4222-8222-222222222222"
LAUNCH_ID = "33333333-3333-4333-8333-333333333333"
ATTESTATION = "secret-launch-attestation"


class FakeAcp:
    def new_session(self, request):
        self.request = request
        return CursorNativeResult(
            "native_created", native_session_id=CONVERSATION_ID, duration_ms=25
        )

    def prompt_session(self, request):
        raise AssertionError("launch must not prompt")


def _launch(tmp_path: Path) -> RelayExecutionContext:
    return RelayExecutionContext(
        job_kind="launch",
        job_id=LAUNCH_ID,
        lease_id="lease-launch",
        surface="cursor-cli",
        surface_version="2026.08.11-e8db854",
        project_id=7,
        checkout=tmp_path,
        native_instruction=native_launch_bootstrap(LAUNCH_ID),
        message_id="44444444-4444-4444-8444-444444444444",
        launch_attestation=ATTESTATION,
    )


def test_lookup_retries_until_the_conversation_map_has_a_session() -> None:
    listings = iter((None, MAPPED_SESSION_ID))
    delays = []

    resolution = resolve_conversation_session(
        CONVERSATION_ID,
        lambda _conversation_id: next(listings),
        sleeper=delays.append,
    )

    assert resolution.session_id == MAPPED_SESSION_ID
    assert resolution.result_code == "identity_resolved"
    assert resolution.attempts == 2
    assert delays == [0.1]


def test_lookup_fails_closed_after_the_bounded_missing_map_window() -> None:
    calls = []
    delays = []

    resolution = resolve_conversation_session(
        CONVERSATION_ID,
        lambda conversation_id: calls.append(conversation_id) or None,
        sleeper=delays.append,
    )

    assert resolution.session_id is None
    assert resolution.result_code == "identity_parse_failed"
    assert resolution.attempts == CURSOR_IDENTITY_LOOKUP_ATTEMPTS
    assert calls == [CONVERSATION_ID] * CURSOR_IDENTITY_LOOKUP_ATTEMPTS
    assert len(delays) == CURSOR_IDENTITY_LOOKUP_ATTEMPTS - 1
    assert CONVERSATION_ID in (resolution.output_snippet or "")
    assert resolution.parse_expectation == ACP_SESSION_PARSE_EXPECTATION


def test_bind_stages_attestation_under_the_mapped_session_not_the_conversation() -> (
    None
):
    handoffs = []

    binding = bind_launch_session(
        CONVERSATION_ID,
        lambda _conversation_id: MAPPED_SESSION_ID,
        lambda launch_id, secret, **kwargs: (
            handoffs.append((launch_id, secret, kwargs)) or True
        ),
        LAUNCH_ID,
        ATTESTATION,
        sleeper=lambda _seconds: None,
    )

    assert binding.result_code == "native_created"
    assert binding.session_id == MAPPED_SESSION_ID
    assert MAPPED_SESSION_ID != CONVERSATION_ID
    assert handoffs == [(LAUNCH_ID, ATTESTATION, {"binding_id": MAPPED_SESSION_ID})]


def test_bind_without_a_sidecar_keeps_the_mapped_session_unknown() -> None:
    binding = bind_launch_session(
        CONVERSATION_ID,
        lambda _conversation_id: MAPPED_SESSION_ID,
        None,
        LAUNCH_ID,
        ATTESTATION,
        sleeper=lambda _seconds: None,
    )

    assert binding.result_code == "attestation_handoff_unavailable"
    assert binding.session_id == MAPPED_SESSION_ID


def test_bind_sidecar_failure_keeps_the_mapped_session_unknown() -> None:
    binding = bind_launch_session(
        CONVERSATION_ID,
        lambda _conversation_id: MAPPED_SESSION_ID,
        lambda *_args, **_kwargs: False,
        LAUNCH_ID,
        ATTESTATION,
        sleeper=lambda _seconds: None,
    )

    assert binding.result_code == "attestation_handoff_failed"
    assert binding.session_id == MAPPED_SESSION_ID


def test_default_lookup_reads_the_conversation_map_directory(tmp_path: Path) -> None:
    assert record_conversation_session(CONVERSATION_ID, MAPPED_SESSION_ID, tmp_path)
    assert (
        conversation_map_lookup(CONVERSATION_ID, map_dir=tmp_path) == MAPPED_SESSION_ID
    )


def test_adapter_reports_and_stages_the_mapped_session(tmp_path: Path) -> None:
    handoffs = []
    lookups = []

    result = build_cursor_adapter(
        acp_port=FakeAcp(),
        identity_lookup=lambda conversation_id: (
            lookups.append(conversation_id) or MAPPED_SESSION_ID
        ),
        attestation_handoff=lambda launch_id, secret, **kwargs: (
            handoffs.append((launch_id, secret, kwargs)) or True
        ),
        sleeper=lambda _seconds: None,
    )(_launch(tmp_path))

    assert lookups == [CONVERSATION_ID]
    assert handoffs == [(LAUNCH_ID, ATTESTATION, {"binding_id": MAPPED_SESSION_ID})]
    assert result.result_code == "native_created"
    assert result.native_session_id == MAPPED_SESSION_ID
    assert result.evidence["result_code"] == "native_created"
    assert result.evidence["native_launch_phase"] == "native_running"
    assert ATTESTATION not in repr(result)


def test_current_cursor_agent_session_new_payload_parses() -> None:
    payload = {
        "sessionId": CONVERSATION_ID,
        "modes": {
            "currentModeId": "agent",
            "availableModes": [{"id": "agent", "name": "Agent"}],
        },
        "models": {"currentModelId": "default[]", "availableModels": []},
    }

    assert session_id_from_native_payload(payload) == CONVERSATION_ID
    assert session_id_from_native_payload({"modes": payload["modes"]}) is None


def test_bind_map_miss_does_not_treat_the_acp_id_as_registered() -> None:
    handoffs = []

    binding = bind_launch_session(
        CONVERSATION_ID,
        lambda _conversation_id: None,
        lambda launch_id, secret, **kwargs: (
            handoffs.append((launch_id, secret, kwargs)) or True
        ),
        LAUNCH_ID,
        ATTESTATION,
        sleeper=lambda _seconds: None,
    )

    assert binding.result_code == "registration_unproven"
    assert binding.session_id == CONVERSATION_ID
    assert handoffs == []


def test_adapter_map_miss_hands_over_a_pending_native(tmp_path: Path) -> None:
    handoffs = []
    result = build_cursor_adapter(
        acp_port=FakeAcp(),
        identity_lookup=lambda _conversation_id: None,
        attestation_handoff=lambda launch_id, secret, **kwargs: (
            handoffs.append((launch_id, secret, kwargs)) or True
        ),
        sleeper=lambda _seconds: None,
    )(_launch(tmp_path))

    assert result.result_code == "native_created"
    assert result.native_session_id == CONVERSATION_ID
    assert result.evidence["native_launch_phase"] == "registration_pending"
    assert handoffs == [(LAUNCH_ID, ATTESTATION, {"binding_id": CONVERSATION_ID})]


def test_unparseable_identity_fails_closed_with_snippet(tmp_path: Path) -> None:
    class UnparseableAcp:
        def new_session(self, request):
            return CursorNativeResult(
                "native_created",
                native_session_id="not-a-session-id",
                duration_ms=25,
            )

        def prompt_session(self, request):
            raise AssertionError("launch must not prompt")

    result = build_cursor_adapter(
        acp_port=UnparseableAcp(),
        identity_lookup=lambda _conversation_id: None,
        attestation_handoff=lambda *_args, **_kwargs: True,
        sleeper=lambda _seconds: None,
    )(_launch(tmp_path))
    durable = redacted_evidence_document(result.evidence)

    assert result.result_code == "not_created"
    assert result.native_session_id is None
    assert result.evidence["result_code"] == "identity_parse_failed"
    assert "not-a-session-id" in str(durable["identity_output_snippet"])
    assert durable["identity_parse_expectation"] == ACP_SESSION_PARSE_EXPECTATION
    assert ATTESTATION not in repr(result)
    assert ATTESTATION not in repr(durable)
