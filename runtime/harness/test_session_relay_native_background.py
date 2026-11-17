"""A held wake names the background command keeping its native alive."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.platform_process import ProcessInfo
from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_contracts.session_control.wake_delivery import NATIVE_TURN_RUNNING_RESULT
from yoke_harness import session_relay_runtime
from yoke_harness.session_launch_containment import supervision_record_path
from yoke_harness.session_relay_native_background import background_children
from yoke_harness.session_relay_native_turn_custody import deferral_for_running_native

pytestmark = pytest.mark.windows

SESSION = "11111111-1111-4111-8111-111111111111"
RECORDED_START = "Mon Aug 24 08:00:00 2026"
NATIVE = 4001


def _proc(pid: int, ppid: int, *argv: str) -> ProcessInfo:
    return ProcessInfo(pid, ppid, tuple(argv), 0.0, Path(argv[0]).name, 0, "me")


#: A native after its turn: an MCP server it owns, and a background ``npm run
#: build`` the Bash tool started under a login shell.
TABLE = (
    _proc(NATIVE, 1, "/usr/local/bin/claude", "-p"),
    _proc(4100, NATIVE, "node", "mcp-server.js"),
    _proc(4110, NATIVE, "/bin/zsh", "-c", "-l", "source snap && eval 'npm run build'"),
    _proc(4120, 4110, "npm", "run", "build"),
)


def _resume_record(state_dir: Path | None = None) -> None:
    supervision_record_path("attempt-1", state_dir).write_text(
        json.dumps(
            {
                "launch_id": "attempt-1",
                "pid": NATIVE,
                "process_start_time": RECORDED_START,
                "native_session_id": SESSION,
                "supervision_kind": "resume",
            }
        ),
        encoding="utf-8",
    )


def _context(workspace: Path):
    return session_relay_runtime.execution_context(
        {
            "job_kind": "wake",
            "job_id": "44444444-4444-4444-8444-444444444444",
            "lease_id": "lease-2",
            "surface": "claude-cli",
            "project_id": 1,
            "target_workspace": str(workspace),
            "target_session_id": SESSION,
            "message_id": "55555555-5555-4555-8555-555555555555",
            "native_instruction": "deliver 55555555-5555-4555-8555-555555555555",
        }
    )


def test_a_shell_child_is_named_by_the_command_under_it() -> None:
    children = background_children(NATIVE, TABLE)

    assert [(c.pid, c.command) for c in children] == [(4120, "npm run build")]


def test_a_shell_with_nothing_under_it_is_named_itself() -> None:
    children = background_children(NATIVE, TABLE[:3])

    assert [(c.pid, c.command) for c in children] == [(4110, "zsh")]


def test_a_native_with_no_shell_children_names_nothing() -> None:
    assert background_children(NATIVE, TABLE[:2]) == ()


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        (("curl", "-H", "Authorization: Bearer s3cr3t", "https://x.test"), "curl"),
        (("/usr/bin/psql", "postgres://u:pw@host/db"), "psql"),
        (("deploy", "API_KEY=s3cr3t"), "deploy"),
        (("sleep", "600"), "sleep 600"),
        (("tool", "a", "b", "c", "d", "e", "f"), "tool a b c d"),
    ],
)
def test_a_command_is_named_without_options_or_credentials(argv, named) -> None:
    table = (_proc(4110, NATIVE, "bash", "-c", "x"), _proc(4120, 4110, *argv))
    (child,) = background_children(NATIVE, table)

    assert child.command == named
    assert "s3cr3t" not in child.command and "pw" not in child.command


def test_a_held_wake_names_the_background_child_and_starts_nothing(
    tmp_path: Path,
) -> None:
    """Live pid, ended turn, live child: the deferral names the child."""
    _resume_record(tmp_path)
    result = deferral_for_running_native(
        _context(tmp_path),
        custody_state_dir=tmp_path,
        start_time_of=lambda pid: RECORDED_START if pid == NATIVE else None,
        children_of=lambda pid: background_children(pid, TABLE),
    )

    assert result is not None
    assert result.result_code == NATIVE_TURN_RUNNING_RESULT
    kept = redacted_evidence_document(result.evidence)
    assert kept["running_native_pid"] == NATIVE
    assert kept["running_native_background_pid"] == 4120
    assert kept["running_native_background_command"] == "npm run build"
    assert kept["running_native_background_count"] == 1


def test_a_held_wake_without_children_still_defers(tmp_path: Path) -> None:
    """Mid-turn or not, a live pid holds the wake; no child is named."""
    _resume_record(tmp_path)
    result = deferral_for_running_native(
        _context(tmp_path),
        custody_state_dir=tmp_path,
        start_time_of=lambda pid: RECORDED_START if pid == NATIVE else None,
        children_of=lambda pid: (),
    )

    assert result is not None
    assert result.result_code == NATIVE_TURN_RUNNING_RESULT
    assert "running_native_background_pid" not in result.evidence


def test_the_runner_starts_no_second_native_behind_a_background_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[str] = []

    def adapter(context):
        spawned.append(context.target_session_id or "")
        return session_relay_runtime.RelayAdapterResult("resumed_running")

    session_relay_runtime.reset_relay_adapters_for_tests()
    session_relay_runtime.register_relay_adapter("claude-cli", adapter)
    monkeypatch.setattr(
        "yoke_harness.session_relay_native_turn_custody.process_start_time",
        lambda pid: RECORDED_START if pid == NATIVE else None,
    )
    monkeypatch.setattr(
        "yoke_contracts.platform_process.process_command_lines", lambda: list(TABLE)
    )
    # The shared isolation fixture redirects the machine cache this reads.
    _resume_record()
    try:
        result = session_relay_runtime.run_registered_job(
            {
                "job_kind": "wake",
                "job_id": "44444444-4444-4444-8444-444444444444",
                "lease_id": "lease-2",
                "surface": "claude-cli",
                "project_id": 1,
                "target_workspace": str(tmp_path),
                "target_session_id": SESSION,
                "message_id": "55555555-5555-4555-8555-555555555555",
                "native_instruction": "deliver 55555555-5555-4555-8555-555555555555",
            }
        )
    finally:
        session_relay_runtime.reset_relay_adapters_for_tests()

    assert result.result_code == NATIVE_TURN_RUNNING_RESULT
    assert result.evidence["running_native_background_pid"] == 4120
    assert spawned == []
