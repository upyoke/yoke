"""Shared scaffolding for the cursor CLI transport's supervised-resume tests.

A supervised spawn writes a custody record and a capture on the machine that
starts it, so tests that only care about the native's own command line keep
both inside their own tree rather than the operator's home.
"""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_harness.session_relay_cursor import CursorCreateRequest, CursorWakeRequest


ATTEMPT_ID = "33333333-3333-4333-8333-333333333333"


class RunningProcess:
    pid = 4321

    def wait(self, timeout=None):
        del timeout
        return 0


def local_supervision(monkeypatch, tmp_path: Path) -> None:
    """Keep the supervised spawn's custody and capture inside the test tree."""
    from yoke_harness import session_relay_native_spawn as spawn_module

    monkeypatch.setattr(
        spawn_module, "record_supervised_native", lambda *_a, **_k: True
    )
    monkeypatch.setattr(
        spawn_module, "cleanup_native_diagnostics", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        spawn_module,
        "native_diagnostic_path",
        lambda reference, **_options: tmp_path / f"{reference}.capture",
    )


def native_argv(command: list[str]) -> list[str]:
    """Return the native the supervisor was told to run, past its own flags."""
    return command[command.index("--") + 1 :]


LAUNCH_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
ATTESTATION = "single-use-secret"
BOOTSTRAP = native_launch_bootstrap(LAUNCH_ID)
CHECK_INBOX = native_wake_instruction("message-1")


def create_request(tmp_path: Path) -> CursorCreateRequest:
    return CursorCreateRequest(
        checkout=tmp_path,
        launch_id=LAUNCH_ID,
        surface_version="2026.08.11-e8db854",
        native_instruction=BOOTSTRAP,
        launch_attestation=ATTESTATION,
        requested_model="composer-2",
    )


def wake_request(tmp_path: Path) -> CursorWakeRequest:
    return CursorWakeRequest(
        checkout=tmp_path,
        target_session_id=SESSION_ID,
        surface_version="2026.08.11-e8db854",
        target_liveness="ended",
        wake_mode="waiting",
        native_instruction=CHECK_INBOX,
        requested_model="composer-2",
        attempt_id=ATTEMPT_ID,
        lease_id="lease-1",
    )


__all__ = [
    "ATTEMPT_ID",
    "ATTESTATION",
    "BOOTSTRAP",
    "CHECK_INBOX",
    "LAUNCH_ID",
    "SESSION_ID",
    "create_request",
    "wake_request",
    "RunningProcess",
    "local_supervision",
    "native_argv",
]
