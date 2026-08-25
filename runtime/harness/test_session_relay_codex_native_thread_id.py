"""Codex wake thread-id resolution: hand-started vs. launched shapes.

Split from ``test_session_relay_codex.py`` (350-line authored cap). Shares
the ``context`` fixture and transport fakes from that module rather than
duplicating them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_harness import session_relay_codex as adapter_module
from yoke_harness.session_relay_codex import (
    ThreadIdUnknownError,
    build_codex_relay_adapter,
)

from runtime.harness.test_session_relay_codex import FakeTransport, context


def test_wake_prefers_stored_native_thread_id_over_hand_started_session_id(
    tmp_path: Path,
) -> None:
    """Hand-started shape: CODEX_SESSION_ID disagrees with the app-server thread."""
    cli = FakeTransport()
    adapter = build_codex_relay_adapter(
        cli_transport=cli,
        desktop_transport=FakeTransport(),
        version_gate=lambda *_args: True,
    )

    result = adapter(
        context(
            tmp_path,
            job_kind="wake",
            target_session_id="hand-started-yoke-session",
            target_native_thread_id="native-thread-42",
        )
    )

    assert result.result_code == "accepted"
    request = cli.calls[0][1]
    assert request.target_session_id == "hand-started-yoke-session"
    assert request.target_thread_id == "native-thread-42"
    assert (
        request.instruction_id
        == "message:message-1:recipient:hand-started-yoke-session"
    )


def test_wake_falls_back_to_session_id_for_launched_shape(tmp_path: Path) -> None:
    """Launched shape: no stored mapping, so the launch-time equality holds."""
    request = adapter_module._request(
        context(tmp_path, job_kind="wake", target_session_id="native-1")
    )[0]

    assert request.target_thread_id == "native-1"


def test_wake_refuses_thread_id_unknown_without_touching_the_transport(
    tmp_path: Path,
) -> None:
    cli = FakeTransport()
    adapter = build_codex_relay_adapter(
        cli_transport=cli,
        desktop_transport=FakeTransport(),
        version_gate=lambda *_args: True,
    )

    result = adapter(context(tmp_path, job_kind="wake", target_session_id=None))

    assert result.result_code == "thread_id_unknown"
    assert result.evidence == {"result_code": "thread_id_unknown"}
    assert cli.calls == []
    with pytest.raises(ThreadIdUnknownError):
        adapter_module._request(
            context(tmp_path, job_kind="wake", target_session_id=None)
        )
