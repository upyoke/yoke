"""Claude relay-owned create, transport, version, and redaction tests."""

from __future__ import annotations

from runtime.harness.session_relay_claude_test_support import (
    BOOTSTRAP as BOOTSTRAP,
    CHECK_INBOX as CHECK_INBOX,
    CLAUDE as CLAUDE,
    CLAUDE_LOCAL_SETTINGS_JSON as CLAUDE_LOCAL_SETTINGS_JSON,
    DIAGNOSTIC_REF as DIAGNOSTIC_REF,
    LAUNCH_ID as LAUNCH_ID,
    MESSAGE_ID as MESSAGE_ID,
    _allow as _allow,
    _context as _context,
    _started as _started,
)


from functools import partial
from itertools import count

import pytest

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_harness.session_relay_claude import (
    ClaudeNativeInvocation,
    run_claude_cli_adapter,
    unsupported_claude_route,
)
from yoke_harness import session_relay_claude, session_relay_native_create
from yoke_harness.session_relay_native_capture_format import compose_capture


@pytest.fixture(autouse=True)
def native_create_clock(monkeypatch):
    monkeypatch.setattr(
        session_relay_claude, "immediate_native_refusal",
        partial(session_relay_native_create.immediate_native_refusal,
                monotonic=partial(next, count(step=1.0)), sleeper=lambda delay: None),
    )


def test_create_starts_a_relay_owned_process_under_the_id_it_chose() -> None:
    invocations: list[ClaudeNativeInvocation] = []

    result = run_claude_cli_adapter(
        _context(),
        create_spawner=lambda invocation: (
            invocations.append(invocation) or _started(invocation)
        ),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    invocation = invocations[0]
    assert invocation.launch_id == LAUNCH_ID
    assert invocation.session_id != LAUNCH_ID
    assert invocation.argv == (
        CLAUDE,
        "-p",
        "--dangerously-skip-permissions",
        "--settings",
        CLAUDE_LOCAL_SETTINGS_JSON,
        "--session-id",
        invocation.session_id,
        "--model",
        "claude-opus-4-1",
        "--name",
        "Session display name",
        BOOTSTRAP,
        "--output-format",
        "json",
    )
    assert result.result_code == "native_created"
    assert result.native_session_id == invocation.session_id
    assert result.evidence["result_code"] == "native_spawned"
    assert result.evidence["native_pid"] == 4242
    # The reference is how any other seat reaches this native's own account.
    assert result.evidence["native_diagnostic_ref"] == DIAGNOSTIC_REF
    assert result.evidence["presentation_preference"] == "local"
    assert result.evidence["presentation_control"] == "disableRemoteControl"
    assert "secret-attestation" not in repr(invocation)


def test_every_create_names_a_session_no_earlier_attempt_used() -> None:
    minted = []
    for _attempt in range(3):
        run_claude_cli_adapter(
            _context(),
            create_spawner=lambda invocation: (
                minted.append(invocation.session_id) or _started(invocation)
            ),
            executable_finder=lambda _name: CLAUDE,
            version_gate=_allow,
        )
    assert len(set(minted)) == 3


def test_native_that_refuses_at_once_is_not_created_and_private(tmp_path) -> None:
    capture = tmp_path / "capture.capture"
    capture.write_bytes(
        compose_capture(
            stdout=b"",
            stderr=b"claude: unknown option --nope\n",
            exit_code=2,
        )
    )

    result = run_claude_cli_adapter(
        _context(),
        create_spawner=lambda invocation: _started(invocation, capture),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == "not_created"
    assert result.native_session_id is None
    assert result.evidence["result_code"] == "child_exited"
    assert result.evidence["exit_code"] == 2
    assert "unknown option" not in repr(result.evidence)
    assert result.private_diagnostic is not None
    assert b"unknown option" in result.private_diagnostic.stderr


def test_spawn_that_never_started_is_outcome_unknown() -> None:
    result = run_claude_cli_adapter(
        _context(),
        create_spawner=lambda _invocation: None,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == "outcome_unknown"
    assert result.evidence["result_code"] == "create_spawn_failed"


def test_spawn_exception_text_never_enters_result() -> None:
    def unavailable(_invocation):
        raise RuntimeError("secret spawn output")

    result = run_claude_cli_adapter(
        _context(),
        create_spawner=unavailable,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == "outcome_unknown"
    assert result.evidence["result_code"] == "native_exception"
    assert "secret spawn output" not in repr(result.evidence)


def test_missing_attestation_refuses_before_native_create() -> None:
    calls = []
    result = run_claude_cli_adapter(
        _context(launch_attestation=None),
        create_spawner=calls.append,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == "not_created"
    assert result.evidence["result_code"] == "launch_attestation_missing"
    assert calls == []


@pytest.mark.parametrize(
    ("surface", "job_kind", "expected"),
    [
        ("claude-desktop", "launch", "not_created"),
        ("claude-desktop", "wake", "unsupported_surface"),
        ("claude-vscode", "launch", "not_created"),
        ("claude-vscode", "wake", "unsupported_surface"),
    ],
)
def test_desktop_and_vscode_routes_remain_typed(surface, job_kind, expected) -> None:
    result = unsupported_claude_route(_context(surface=surface, job_kind=job_kind))
    assert result.result_code == expected
    assert result.evidence["result_code"] == "unsupported_surface"


@pytest.mark.parametrize(
    ("job_kind", "expected"),
    [("launch", "not_created"), ("wake", "failed")],
)
def test_missing_cli_is_discovered_before_native_invocation(
    job_kind,
    expected,
) -> None:
    invocations = []
    result = run_claude_cli_adapter(
        _context(
            job_kind=job_kind,
            native_instruction=BOOTSTRAP if job_kind == "launch" else CHECK_INBOX,
            target_session_id="native-session-1" if job_kind == "wake" else None,
            target_liveness="ended" if job_kind == "wake" else None,
            wake_mode="waiting" if job_kind == "wake" else None,
        ),
        create_spawner=invocations.append,
        executable_finder=lambda _name: None,
        version_gate=_allow,
    )

    assert result.result_code == expected
    assert result.evidence["result_code"] == "executable_unavailable"
    assert invocations == []


@pytest.mark.parametrize(
    ("context", "code"),
    [
        (_context(native_instruction="secret body"), "instruction_invalid"),
        (
            _context(
                job_id="not-a-uuid",
                native_instruction=(native_launch_bootstrap("not-a-uuid")),
            ),
            "native_session_invalid",
        ),
    ],
)
def test_invalid_launch_inputs_are_refused_before_native_process(context, code) -> None:
    calls = []
    result = run_claude_cli_adapter(
        context,
        create_spawner=calls.append,
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == "not_created"
    assert result.evidence["result_code"] == code
    assert calls == []
