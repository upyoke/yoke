"""A local universe adopts the native it launched, or keeps supervising it.

A launch handle is the only machine-local record binding a launched session
to the pid that served it. The relay's process-death report reads it, and so
does the fold that turns a print-mode native's own exit result into that
session's token totals. Writing it is the last step of delivering the launch
instruction, so a hook entry that never settled the launch projection wrote
no handle at all: the session's death went unreported until the stale sweep,
and its measured usage stayed unavailable with the counters sitting on disk.
"""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout

import pytest


LAUNCH_ID = "11111111-1111-4111-8111-111111111111"
LAUNCHED_SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MESSAGE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
RESULT_REQUEST_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
CONVERSATION_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"

DELIVERED_INSTRUCTIONS = (
    f"=== BEGIN YOKE LAUNCH DELIVERY YOKE_SESSION_LAUNCH:{LAUNCH_ID}:"
    f"{MESSAGE_ID} ===\n--- begin instructions ---\nwork\n"
    "--- end instructions ---\n"
)


class _LaunchedNative:
    """One launched native staged the way its own machine stages one.

    Custody, handles, and usage watermarks each resolve from a different
    machine-local root, and the defect this suite covers was a writer and a
    reader disagreeing about one of them, so every root is bound here rather
    than left to the developer's real machine home.
    """

    def __init__(self, tmp_path, monkeypatch) -> None:
        from yoke_harness import session_launch_handles
        from yoke_harness.session_launch_containment import (
            record_supervised_native,
            supervision_record_path,
        )

        self.relay_state = tmp_path / "relay-state"
        self.relay_state.mkdir(parents=True)
        self.handles = tmp_path / "session-native-handles"
        home = tmp_path / "yoke-home"
        home.mkdir()

        monkeypatch.setattr(
            "yoke_cli.config.machine_config.cache_dir",
            lambda *_a, **_k: tmp_path / "machine-cache",
        )
        monkeypatch.setattr(
            "yoke_cli.config.machine_config.yoke_home",
            lambda *_a, **_k: home,
        )
        monkeypatch.setattr(
            session_launch_handles,
            "native_handle_directory",
            lambda: (
                self.handles.mkdir(mode=0o700, parents=True, exist_ok=True)
                or self.handles
            ),
        )
        assert record_supervised_native(LAUNCH_ID, os.getpid())
        self.custody = supervision_record_path(LAUNCH_ID)
        self.handle = self.handles / f"{LAUNCH_ID}.json"

    def run_opening_hook(
        self,
        monkeypatch,
        *,
        stdout: str,
        launch_context: bool = True,
    ) -> int:
        """Drive the installed local-universe entry over one opening hook."""
        from yoke_core.hooks import local_entry
        from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV

        if launch_context:
            monkeypatch.setenv(
                LAUNCH_CONTEXT_ENV,
                json.dumps({"launch_id": LAUNCH_ID, "attestation": "token"}),
            )
        else:
            monkeypatch.delenv(LAUNCH_CONTEXT_ENV, raising=False)
        for name, value in (
            ("detect_executor", lambda: "cursor"),
            ("record_client_anchor", lambda *_a, **_k: None),
            ("capture_codex_session", lambda *_a, **_k: None),
            ("ensure_user_lifecycle_hooks_for_executor", lambda *_a: None),
            ("relay_identity_payload", lambda *_a, **_k: {}),
            ("record_model_facts_shipped", lambda *_a, **_k: None),
            ("confirmed_served_model", lambda *_a, **_k: None),
            ("resolve_capability", lambda *_a, **_k: None),
            ("run_event", lambda *_a, **_k: (stdout, 0)),
        ):
            monkeypatch.setattr(local_entry, name, value)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return local_entry.evaluate_local_hook(
                "SessionStart",
                json.dumps({"session_id": LAUNCHED_SESSION}),
            )


class _RelayInventory:
    relay_id = "machine:test"
    machine_id = "machine-1"
    project_ids = (1,)


class _RecordingDispatcher:
    """A dispatcher that records its reports and settles none of them."""

    success = True
    error = None
    result = {"ended": [], "skipped": []}

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, *, function_id, target, payload, timeout_s):
        del target, timeout_s
        self.calls.append({"function_id": function_id, **payload})
        return self


def test_a_delivered_launch_is_adopted_and_stops_being_supervised(
    monkeypatch,
    tmp_path,
) -> None:
    """Delivering the instruction hands the native from custody to a handle."""
    native = _LaunchedNative(tmp_path, monkeypatch)

    assert native.run_opening_hook(monkeypatch, stdout=DELIVERED_INSTRUCTIONS) == 0

    assert native.handle.is_file(), "the launched native was never adopted"
    handle = json.loads(native.handle.read_text())
    assert handle["target_session_id"] == LAUNCHED_SESSION
    assert handle["launch_id"] == LAUNCH_ID
    assert not native.custody.exists(), (
        "custody outlived the delivery that proved registration"
    )


@pytest.mark.parametrize(
    "stdout, launch_context, undelivered",
    [
        ("", True, "the hook rendered no launch delivery"),
        (DELIVERED_INSTRUCTIONS, False, "the native carried no launch context"),
    ],
)
def test_an_undelivered_launch_is_neither_adopted_nor_released(
    monkeypatch,
    tmp_path,
    stdout: str,
    launch_context: bool,
    undelivered: str,
) -> None:
    """Adoption follows delivery, so custody survives every other outcome.

    Adopting a native whose mandate never reached it would retire the record
    the containment sweep terminates an unattended process by, and the one
    the launch settlement closes a launch that died coming up by.
    """
    native = _LaunchedNative(tmp_path, monkeypatch)

    assert (
        native.run_opening_hook(
            monkeypatch,
            stdout=stdout,
            launch_context=launch_context,
        )
        == 0
    )

    assert not native.handle.exists(), f"adopted though {undelivered}"
    assert native.custody.is_file(), f"custody dropped though {undelivered}"


def test_the_adopted_handle_carries_the_native_reading_to_the_relay(
    monkeypatch,
    tmp_path,
) -> None:
    """The handle adoption writes is what the death-and-usage report reads.

    This is what adopting is for: the counters a print-mode native states as
    it exits are unreachable until some machine-local record names the
    session behind that launch. Reporting twice counts the turn once, because
    a handle the control plane has not settled is read again next poll.
    """
    from runtime.harness.session_usage_test_support import cursor_result_payload
    from yoke_contracts.session_identity import ANCHORS_DIR_NAME
    from yoke_contracts.session_usage_facts import usage_from_document
    from yoke_harness.session_relay_native_capture_format import compose_capture
    from yoke_harness.session_relay_native_diagnostics import (
        diagnostic_reference,
        native_diagnostic_path,
        write_native_capture,
    )
    from yoke_harness.session_relay_process_liveness import (
        report_verified_dead_sessions,
    )

    native = _LaunchedNative(tmp_path, monkeypatch)
    native.run_opening_hook(monkeypatch, stdout=DELIVERED_INSTRUCTIONS)
    write_native_capture(
        native_diagnostic_path(
            diagnostic_reference(LAUNCH_ID),
            state_dir=native.relay_state,
            create=True,
        ),
        compose_capture(
            stdout=json.dumps(
                cursor_result_payload(
                    session_id=CONVERSATION_ID,
                    request_id=RESULT_REQUEST_ID,
                    input_tokens=93466,
                    output_tokens=1537,
                    cache_read_tokens=77056,
                    cache_write_tokens=0,
                )
            ).encode(),
            stderr=b"",
            exit_code=0,
        ),
    )

    def one_poll() -> dict:
        dispatcher = _RecordingDispatcher()
        report_verified_dead_sessions(
            dispatcher,
            _RelayInventory(),
            state_dir=native.relay_state,
            anchors_dir=tmp_path / ANCHORS_DIR_NAME,
            start_time_of=lambda _pid: None,
        )
        return dispatcher.calls[0]["sessions"][0]

    reported = one_poll()
    assert reported["session_id"] == LAUNCHED_SESSION
    assert reported["evidence"]["launch_id"] == LAUNCH_ID
    counted = usage_from_document(reported["usage_totals"]).models[0]
    assert (
        counted.input,
        counted.output,
        counted.cached_input,
        counted.cache_write,
    ) == (93466, 1537, 77056, 0)
    assert usage_from_document(one_poll()["usage_totals"]).models[0] == counted
