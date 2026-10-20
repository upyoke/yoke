"""A cold or stuck resident never holds a hook past its budget.

The budget is ``YOKE_HOOK_TOTAL_TIMEOUT_MS`` from the hook process's own
start, capped below every harness's hook timeout. The resident listens
before it loads the evaluator, so a cold one is waited on, not duplicated.
"""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from yoke_cli import hook_resident_client as client
from yoke_cli.commands.adapters import hooks
from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS
from yoke_contracts.hook_budget import harness_budget_ceiling_ms, hook_budget_ms
from yoke_contracts.hook_evaluator_protocol import (
    HookEvaluatorRequest,
    receive_frame,
    send_frame,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def paths(monkeypatch):
    # Unix socket paths are short; pytest's tmp_path can exceed the limit.
    state_dir = Path(tempfile.mkdtemp(prefix="yhb-"))
    resident = client.ResidentPaths(
        state_dir=state_dir,
        socket=state_dir / "r.sock",
        lock=state_dir / "r.lock",
        log=state_dir / "r.log",
    )
    monkeypatch.setattr(client, "resident_paths", lambda: resident)
    monkeypatch.setenv("YOKE_HOOK_TOTAL_TIMEOUT_MS", "1000")
    yield resident
    for path in state_dir.iterdir():
        path.unlink()
    state_dir.rmdir()


def _launch(monkeypatch, code: str) -> list[subprocess.Popen]:
    launched: list[subprocess.Popen] = []

    def start(_paths, _environment):
        launched.append(subprocess.Popen([sys.executable, "-c", code]))
        return launched[-1]

    monkeypatch.setattr(client, "_start_resident", start)
    return launched


def _evaluate() -> tuple[client.ResidentUnavailable, float]:
    started = time.monotonic()
    with pytest.raises(client.ResidentUnavailable) as raised:
        client.evaluate_with_resident(
            "PreToolUse", "{}", client_started_monotonic=started
        )
    return raised.value, time.monotonic() - started


def test_a_loading_resident_is_waited_on_only_inside_the_budget(paths) -> None:
    # Bound and listening but still loading: it never answers.
    loading = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    loading.bind(str(paths.socket))
    loading.listen(8)
    try:
        error, elapsed = _evaluate()
    finally:
        loading.close()
    assert error.code == "YOKE_HOOK_RESIDENT_TIMEOUT"
    assert elapsed < 1.3, f"waited {elapsed:.2f}s on a 1s budget"


def test_a_resident_that_never_listens_ends_inside_the_budget(
    paths, monkeypatch
) -> None:
    launched = _launch(monkeypatch, "import time; time.sleep(30)")
    try:
        error, elapsed = _evaluate()
    finally:
        for process in launched:
            process.kill()
            process.wait()
    assert error.code == "YOKE_HOOK_RESIDENT_UNREACHABLE"
    assert len(launched) == 1
    assert elapsed < 1.3, f"waited {elapsed:.2f}s on a 1s budget"


def test_a_launched_resident_that_exits_ends_the_wait_at_once(
    paths, monkeypatch
) -> None:
    monkeypatch.setenv("YOKE_HOOK_TOTAL_TIMEOUT_MS", "8000")
    _launch(monkeypatch, "raise SystemExit(3)")
    error, elapsed = _evaluate()
    assert error.code == "YOKE_HOOK_RESIDENT_START_FAILED"
    assert "status 3" in error.detail
    assert str(paths.log) == str(error.log_path)
    assert elapsed < 4.0, f"waited {elapsed:.2f}s for a dead resident"


def test_a_resident_that_only_ever_restarts_gives_up_inside_the_budget(
    paths, monkeypatch
) -> None:
    monkeypatch.setattr(client, "_connect", lambda *_args: Mock())
    monkeypatch.setattr(
        client,
        "_exchange",
        lambda *_args: {
            "status": "restart",
            "loaded_revision": "aaaaaaaaaaaa",
            "requested_revision": "bbbbbbbbbbbb",
        },
    )
    error, elapsed = _evaluate()
    assert elapsed < 1.3, f"waited {elapsed:.2f}s on a 1s budget"
    assert error.code == "YOKE_HOOK_RESIDENT_UNREACHABLE"
    # Both revisions are named, so a stuck upgrade reads from one line.
    assert "aaaaaaaaaaaa" in error.detail and "bbbbbbbbbbbb" in error.detail
    assert error.resident_wait_ms > 0


def test_a_cold_resident_listens_before_loading_and_answers_once_ready(
    paths,
) -> None:
    from yoke_harness.hook_resident import _ResidentServer

    lock_fd = os.open(paths.lock, os.O_CREAT | os.O_RDWR, 0o600)
    server = _ResidentServer(str(paths.socket), lock_fd)
    try:
        # Construction binds without importing the evaluator.
        assert not hasattr(server, "evaluate_inprocess")
        peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        peer.settimeout(5)
        peer.connect(str(paths.socket))
        request = HookEvaluatorRequest(
            event_name="PreToolUse",
            stdin="{}",
            dry_run=True,
            pid=41001,
            ppid=41000,
            cwd="/tmp",
            environment={},
            revision="unknown",
        )
        send_frame(peer, request.to_mapping())
        # Loading finishes after the caller queued; the queued call is answered.
        server.evaluate = lambda _request: (
            {"status": "ok", "stdout": "ready", "stderr": "", "exit_code": 0},
            None,
        )
        server.handle_request()
        assert receive_frame(peer)["stdout"] == "ready"
        peer.close()
    finally:
        server.server_close()
        os.close(lock_fd)


def test_the_budget_stays_below_every_harness_hook_timeout(monkeypatch) -> None:
    shortest = min(s.hook_timeout_seconds for s in HARNESS_MACHINE_HOOKS.values())
    assert harness_budget_ceiling_ms() < shortest * 1000
    assert hook_budget_ms({}) == 10000
    assert hook_budget_ms({"YOKE_HOOK_TOTAL_TIMEOUT_MS": "3600000"}) == (
        harness_budget_ceiling_ms()
    )
    assert hook_budget_ms({"YOKE_HOOK_TOTAL_TIMEOUT_MS": "-1"}) == 10000


@pytest.mark.parametrize("harness_dir", ["claude", "codex", "cursor"])
def test_manifests_publish_the_harness_hook_timeout(harness_dir: str) -> None:
    manifest = json.loads(
        (REPO_ROOT / "runtime/harness" / harness_dir / "manifest.json").read_text()
    )
    harness_id = manifest["harness_id"]
    expected = HARNESS_MACHINE_HOOKS[harness_id].hook_timeout_seconds
    assert manifest["machine_hooks"]["hook_timeout_seconds"] == expected


def test_cursor_hook_entries_carry_the_declared_timeout() -> None:
    hooks_json = json.loads((REPO_ROOT / "runtime/harness/cursor/hooks.json").read_text())
    declared = HARNESS_MACHINE_HOOKS["cursor"].hook_timeout_seconds
    timeouts = {
        entry["timeout"] for entries in hooks_json["hooks"].values() for entry in entries
    }
    assert timeouts == {declared}


def test_a_spent_budget_refuses_by_name_instead_of_falling_back(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("YOKE_HOOK_TOTAL_TIMEOUT_MS", "1000")
    monkeypatch.setenv("YOKE_EXECUTOR", "claude-code")
    # The hook process already spent its whole budget waiting on the resident.
    monkeypatch.setattr("yoke_cli.hook_client_wall._process_age", lambda: 1.5)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    def timed_out(*_args, **_kwargs):
        raise client.ResidentUnavailable(
            "YOKE_HOOK_RESIDENT_TIMEOUT",
            "resident did not answer inside the hook budget",
            log_path=tmp_path / "resident.log",
        )

    monkeypatch.setattr(client, "evaluate_with_resident", timed_out)
    monkeypatch.setattr(
        hooks,
        "_evaluate_inprocess",
        lambda *args, **kwargs: pytest.fail("a spent budget must not fall back"),
    )
    assert hooks.hook_evaluate(["PreToolUse"]) == 2
    err = capsys.readouterr().err
    assert "hook_budget_exhausted: YOKE_HOOK_RESIDENT_TIMEOUT" in err
    assert "yoke hook resident restart" in err
    assert str(tmp_path / "resident.log") in err
