"""Cursor launch registration proof and failed-create reap.

Registration is proven from the conversation map alone: launch drives its
one bootstrap prompt through ACP and nothing else, so a map miss never
triggers a second turn on a second transport.
"""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_harness.session_launch_containment import record_supervised_native
from yoke_harness.session_relay_cursor import (
    CursorNativeResult,
    build_cursor_adapter,
)
from yoke_harness.session_relay_cursor_registration import complete_bound_launch
from yoke_harness.session_relay_runtime import RelayExecutionContext


CONVERSATION_ID = "11111111-1111-4111-8111-111111111111"
MAPPED_SESSION_ID = "22222222-2222-4222-8222-222222222222"
LAUNCH_ID = "33333333-3333-4333-8333-333333333333"
ATTESTATION = "secret-launch-attestation"


class FakeAcp:
    def new_session(self, request):
        return CursorNativeResult(
            "native_created",
            native_session_id=CONVERSATION_ID,
            duration_ms=25,
            phase="spawn",
            conversation_store="acp",
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


def test_a_later_poll_registers_without_any_second_turn(tmp_path: Path) -> None:
    """A map miss on the first poll still resolves within the same wait —
    with no second turn on any other transport."""
    listings = iter((None, MAPPED_SESSION_ID))
    handoffs = []

    result = complete_bound_launch(
        _launch(tmp_path),
        CursorNativeResult(
            "native_created", CONVERSATION_ID, duration_ms=10, conversation_store="acp"
        ),
        lambda _conversation_id: next(listings, MAPPED_SESSION_ID),
        lambda launch_id, secret, **kwargs: (
            handoffs.append((launch_id, secret, kwargs)) or True
        ),
        sleeper=lambda _seconds: None,
        wait_seconds=1.0,
    )

    assert result.result_code == "native_created"
    assert result.native_session_id == MAPPED_SESSION_ID
    assert result.evidence["native_launch_phase"] == "native_running"
    assert result.evidence["conversation_store"] == "acp"
    assert handoffs == [(LAUNCH_ID, ATTESTATION, {"binding_id": MAPPED_SESSION_ID})]


def test_unproven_registration_hands_over_a_pending_native(tmp_path: Path) -> None:
    """A slow cold start is a native still coming up, not a failed create."""
    import subprocess
    import sys

    handoffs = []
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        assert record_supervised_native(
            LAUNCH_ID,
            process.pid,
            native_session_id=CONVERSATION_ID,
            state_dir=tmp_path,
        )
        result = complete_bound_launch(
            _launch(tmp_path),
            CursorNativeResult(
                "native_created",
                CONVERSATION_ID,
                duration_ms=10,
                conversation_store="acp",
            ),
            lambda _conversation_id: None,
            lambda launch_id, secret, **kwargs: (
                handoffs.append((launch_id, secret, kwargs)) or True
            ),
            sleeper=lambda _seconds: None,
            wait_seconds=0.5,
            state_dir=tmp_path,
        )

        assert result.result_code == "native_created"
        assert result.native_session_id == CONVERSATION_ID
        assert result.evidence["native_launch_phase"] == "registration_pending"
        assert result.evidence["conversation_store"] == "acp"
        # The attestation rides the ACP conversation id, which is the id a
        # Cursor session registers under, so a late first hook can still bind.
        assert handoffs == [(LAUNCH_ID, ATTESTATION, {"binding_id": CONVERSATION_ID})]
        # Custody stays with the sweep, which reaps only past the deadline.
        assert process.poll() is None
        assert (tmp_path / "session-launch-supervision" / f"{LAUNCH_ID}.json").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_unparseable_native_identity_still_reaps_the_supervised_native(
    tmp_path: Path,
) -> None:
    import subprocess
    import sys

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        assert record_supervised_native(
            LAUNCH_ID,
            process.pid,
            native_session_id="not-a-uuid",
            state_dir=tmp_path,
        )
        result = complete_bound_launch(
            _launch(tmp_path),
            CursorNativeResult("native_created", "not-a-uuid", duration_ms=10),
            lambda _conversation_id: None,
            lambda *_args, **_kwargs: True,
            sleeper=lambda _seconds: None,
            wait_seconds=0.5,
            state_dir=tmp_path,
        )

        assert result.result_code == "not_created"
        assert result.evidence["result_code"] == "identity_parse_failed"
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_adapter_spawn_exception_names_the_spawn_phase(tmp_path: Path) -> None:
    class Exploding:
        def new_session(self, request):
            raise OSError("spawn refused")

        def prompt_session(self, request):
            raise AssertionError("launch must not prompt")

    result = build_cursor_adapter(
        acp_port=Exploding(),
        identity_lookup=lambda _conversation_id: None,
        attestation_handoff=lambda *_args, **_kwargs: True,
        sleeper=lambda _seconds: None,
    )(_launch(tmp_path))

    assert result.result_code == "outcome_unknown"
    assert result.evidence["result_code"] == "transport_exception"
    assert result.evidence["native_launch_phase"] == "spawn"
    assert ATTESTATION not in repr(result)


def test_transport_phase_survives_a_mapped_bind(tmp_path: Path) -> None:
    result = build_cursor_adapter(
        acp_port=FakeAcp(),
        identity_lookup=lambda _conversation_id: MAPPED_SESSION_ID,
        attestation_handoff=lambda *_args, **_kwargs: True,
        sleeper=lambda _seconds: None,
    )(_launch(tmp_path))

    assert result.result_code == "native_created"
    assert result.evidence["native_launch_phase"] == "native_running"
    assert result.evidence["conversation_store"] == "acp"
