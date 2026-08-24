"""Opt-in live probe; run only when a disposable session is acceptable::
    YOKE_RUN_LIVE_CLAUDE_BACKGROUND_RESUME=I_ACCEPT_DISPOSABLE_SESSION \
      .venv/bin/pytest -q -s runtime/harness/test_claude_background_resume_live.py
Native streams stay in the printed owner-only capture; pytest output is redacted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Callable
from uuid import UUID, uuid4

import pytest

from yoke_harness import session_relay_claude as claude_module
from yoke_harness import session_relay_claude_identity as identity_module
from yoke_harness import session_relay_claude_process as process_module
from yoke_harness.session_relay_environment import native_session_environment


_LIVE_OPT_IN = "I_ACCEPT_DISPOSABLE_SESSION"
_LIVE_OPT_IN_ENV = "YOKE_RUN_LIVE_CLAUDE_BACKGROUND_RESUME"
_REQUIRED_VERSION = "2.1.241"
_VERSION_PATTERN = re.compile(rf"(?<![0-9.]){re.escape(_REQUIRED_VERSION)}(?![0-9.])")
_INITIAL_WAIT_ATTEMPTS = 30
_INITIAL_WAIT_INTERVAL_SECONDS = 0.5
_RESUME_INSTRUCTION = "Disposable Yoke resume probe. Reply RESUMED and stop. Do not use tools or modify files."


class _ProbeFailure(RuntimeError):
    pass


class _PrivateNativeCapture:
    def __init__(self) -> None:
        descriptor, path = tempfile.mkstemp(
            prefix="yoke-claude-background-resume-",
            suffix=".log",
        )
        os.fchmod(descriptor, 0o600)
        self.path = Path(path).resolve()
        self._stream = os.fdopen(descriptor, "ab", buffering=0)
        self.steps: list[dict[str, object]] = []

    def close(self) -> None:
        self._stream.close()

    def append(self, label, stdout, stderr, result, exception) -> None:
        stdout_bytes = stdout.seek(0, os.SEEK_END)
        stderr_bytes = stderr.seek(0, os.SEEK_END)
        stdout.seek(0)
        stderr.seek(0)
        metadata = {
            "label": label,
            "returncode": result.returncode if result else None,
            "duration_ms": result.duration_ms if result else None,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "exception_type": type(exception).__name__ if exception else None,
        }
        self._stream.write(b"\n=== native step ===\n")
        self._stream.write(json.dumps(metadata, sort_keys=True).encode("utf-8"))
        self._stream.write(b"\n--- stdout ---\n")
        shutil.copyfileobj(stdout, self._stream)
        self._stream.write(b"\n--- stderr ---\n")
        shutil.copyfileobj(stderr, self._stream)
        self._stream.write(b"\n=== end native step ===\n")
        self.steps.append(metadata)


def _recorded_call(
    capture: _PrivateNativeCapture,
    label: str,
    call: Callable[[], process_module.ClaudeProcessResult],
) -> process_module.ClaudeProcessResult:
    result = None
    with tempfile.TemporaryFile(mode="w+b") as stdout_spool:
        with tempfile.TemporaryFile(mode="w+b") as stderr_spool:
            spools = {"stdout": stdout_spool, "stderr": stderr_spool}
            original_drain = process_module._drain

            def recording_drain(stream, retained: dict[str, bytes], name: str) -> None:
                bounded = bytearray()
                try:
                    while True:
                        chunk = stream.read(process_module._READ_CHUNK_BYTES)
                        if not chunk:
                            break
                        spools[name].write(chunk)
                        available = (
                            process_module.CLAUDE_STREAM_OUTPUT_LIMIT_BYTES
                            - len(bounded)
                        )
                        if available > 0:
                            bounded.extend(chunk[:available])
                except (OSError, ValueError):
                    pass
                retained[name] = bytes(bounded)

            process_module._drain = recording_drain
            exception = None
            try:
                result = call()
                return result
            except BaseException as caught:
                exception = caught
                raise
            finally:
                process_module._drain = original_drain
                capture.append(label, stdout_spool, stderr_spool, result, exception)


def _agent_states(output: str, short_id: str, actual_id: str) -> tuple[bool, bool]:
    try:
        document = json.loads(output)
    except (TypeError, ValueError):
        return False, False
    if isinstance(document, dict):
        document = document.get("agents", document.get("sessions"))
    if not isinstance(document, list):
        return False, False
    row = next(
        (
            candidate
            for candidate in document
            if isinstance(candidate, dict)
            and str(
                candidate.get("id")
                or candidate.get("agentId")
                or candidate.get("shortId")
                or ""
            )
            == short_id
            and str(candidate.get("sessionId") or "") == actual_id
        ),
        {},
    )
    pid = row.get("pid")
    waiting = row.get("state") == "blocked"
    waiting = waiting and row.get("status") in {"idle", "waiting"} and bool(pid)
    return waiting, row.get("state") == "stopped" and not pid


@pytest.mark.skipif(
    os.environ.get(_LIVE_OPT_IN_ENV) != _LIVE_OPT_IN,
    reason=f"set {_LIVE_OPT_IN_ENV}={_LIVE_OPT_IN} to create a disposable session",
)
def test_stopped_claude_background_session_accepts_production_resume_argv() -> None:
    executable = claude_module.discover_claude_cli()
    if executable is None:
        raise _ProbeFailure("Claude CLI is unavailable")
    isolated = tempfile.TemporaryDirectory(prefix="yoke-claude-resume-project-")
    temp_root = Path(isolated.name).resolve()
    temp_parent = Path(tempfile.gettempdir()).resolve()
    if (
        temp_root.is_symlink()
        or temp_root.parent != temp_parent
        or not temp_root.name.startswith("yoke-claude-resume-project-")
    ):
        raise _ProbeFailure("isolated Claude temp root failed validation")
    os.chmod(temp_root, 0o700)
    cwd = temp_root / "project"
    cwd.mkdir(mode=0o700)
    isolated_project = not any(cwd.iterdir())
    if not isolated_project:
        isolated.cleanup()
        raise _ProbeFailure("isolated Claude project is not empty")
    native_environment = native_session_environment(
        executor="claude-code",
        executor_version=_REQUIRED_VERSION,
        provider="anthropic",
        markers={"CLAUDE_CODE_ENTRYPOINT": "cli"},
    )

    def native(*argv: str) -> process_module.ClaudeProcessResult:
        return process_module.run_bounded_claude_process(
            argv,
            cwd=cwd,
            environment=native_environment,
            timeout_seconds=claude_module.CLAUDE_NATIVE_TIMEOUT_SECONDS,
        )

    capture = _PrivateNativeCapture()
    print(f"CLAUDE_RESUME_PRIVATE_CAPTURE={capture.path}")

    def record(label, call) -> process_module.ClaudeProcessResult:
        return _recorded_call(capture, label, call)

    def command(label: str, *argv: str) -> process_module.ClaudeProcessResult:
        return record(label, lambda: native(*argv))

    def roster(label: str) -> process_module.ClaudeProcessResult:
        return command(label, executable, "agents", "--all", "--json")

    short_id = None
    initial_turn_persisted = False
    initial_wait_state_ready = False
    initial_nonce_seen = False
    initial_wait_attempts = 0
    initial_wait_ms = 0
    stopped_state_seen = False
    stopped_wait_attempts = 0
    resume_succeeded = False
    cleanup_completed = False
    temp_root_removed = False
    failure: _ProbeFailure | None = None
    try:
        version = command("version", executable, "--version")
        if version.returncode or not _VERSION_PATTERN.search(
            f"{version.stdout}\n{version.stderr}"
        ):
            raise _ProbeFailure("installed Claude CLI version mismatch")

        requested_id = str(uuid4())
        nonce_suffix = uuid4().hex
        ready_nonce = f"YOKE_READY_{nonce_suffix}"
        launch_instruction = f"Disposable Yoke resume probe. Reply with the concatenation of YOKE_READY_ and {nonce_suffix}, then use AskUserQuestion to ask Should the probe continue? Wait for input; do not modify files."
        launch = claude_module.ClaudeNativeInvocation(
            executable,
            cwd,
            requested_id,
            _REQUIRED_VERSION,
            launch_instruction,
        )
        launched = command(
            "launch", *launch.argv[:-2], "--safe-mode", *launch.argv[-2:]
        )
        if launched.returncode:
            raise _ProbeFailure("Claude background launch exited nonzero")
        short_id = identity_module.background_agent_id(launched)
        if short_id is None:
            raise _ProbeFailure("Claude background launch identity was not parseable")

        lookup_count = 0

        def lookup() -> process_module.ClaudeProcessResult:
            nonlocal lookup_count
            lookup_count += 1
            return record(
                f"identity_lookup_{lookup_count}",
                lambda: claude_module.lookup_claude_session(launch),
            )

        resolution = identity_module.resolve_background_session(short_id, lookup)
        if resolution.session_id is None:
            raise _ProbeFailure("Claude background session identity did not resolve")
        actual_id = str(UUID(resolution.session_id))

        wait_started = time.monotonic()
        for initial_wait_attempts in range(1, _INITIAL_WAIT_ATTEMPTS + 1):
            agents = roster(f"initial_agents_{initial_wait_attempts}")
            logs = command(
                f"initial_logs_{initial_wait_attempts}", executable, "logs", short_id
            )
            initial_wait_state_ready, _ = _agent_states(
                agents.stdout, short_id, actual_id
            )
            initial_nonce_seen = ready_nonce in f"{logs.stdout}\n{logs.stderr}"
            if agents.returncode == logs.returncode == 0 and (
                initial_wait_state_ready and initial_nonce_seen
            ):
                initial_turn_persisted = True
                break
            if initial_wait_attempts < _INITIAL_WAIT_ATTEMPTS:
                time.sleep(_INITIAL_WAIT_INTERVAL_SECONDS)
        initial_wait_ms = max(0, int((time.monotonic() - wait_started) * 1000))
        if not initial_turn_persisted:
            raise _ProbeFailure("initial Claude background turn did not persist")

        stopped = command("stop_before_resume", executable, "stop", short_id)
        if stopped.returncode:
            raise _ProbeFailure("Claude background session did not stop cleanly")
        for stopped_wait_attempts in range(1, _INITIAL_WAIT_ATTEMPTS + 1):
            agents = roster(f"stopped_agents_{stopped_wait_attempts}")
            _, stopped_state_seen = _agent_states(agents.stdout, short_id, actual_id)
            if agents.returncode == 0 and stopped_state_seen:
                break
            time.sleep(_INITIAL_WAIT_INTERVAL_SECONDS)
        if not stopped_state_seen:
            raise _ProbeFailure("Claude background session did not reach stopped state")

        resume = claude_module.ClaudeNativeInvocation(
            executable,
            cwd,
            actual_id,
            _REQUIRED_VERSION,
            _RESUME_INSTRUCTION,
            resume=True,
        )
        resumed = record(
            "production_resume", lambda: claude_module.run_claude_process(resume)
        )
        if resumed.returncode:
            raise _ProbeFailure("production Claude resume argv exited nonzero")
        try:
            observed_id = str(UUID(str(json.loads(resumed.stdout)["session_id"])))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise _ProbeFailure(
                "production Claude resume identity was malformed"
            ) from None
        if observed_id != actual_id:
            raise _ProbeFailure("production Claude resume returned another identity")
        resume_succeeded = True
    except _ProbeFailure as caught:
        failure = caught
    finally:
        if short_id is not None:
            stop_result = command("cleanup_stop", executable, "stop", short_id)
            remove_result = command("cleanup_remove", executable, "rm", short_id)
            cleanup_completed = remove_result.returncode == 0
            if stop_result.returncode and not cleanup_completed and failure is None:
                failure = _ProbeFailure("Claude background cleanup failed")
        isolated.cleanup()
        temp_root_removed = not temp_root.exists()
        if not temp_root_removed and failure is None:
            failure = _ProbeFailure("isolated Claude temp root cleanup failed")
        capture.close()
        summary = {
            "capture_path": str(capture.path),
            "capture_mode": oct(capture.path.stat().st_mode & 0o777),
            "steps": capture.steps,
            "initial_wait_state_ready": initial_wait_state_ready,
            "initial_nonce_seen": initial_nonce_seen,
            "initial_wait_attempts": initial_wait_attempts,
            "initial_wait_ms": initial_wait_ms,
            "stopped_state_seen": stopped_state_seen,
            "resume_succeeded": resume_succeeded,
            "cleanup_completed": cleanup_completed,
            "safe_mode_requested": True,
            "isolated_project": isolated_project,
            "temp_root_removed": temp_root_removed,
        }
        print("CLAUDE_RESUME_REDACTED_SUMMARY=" + json.dumps(summary, sort_keys=True))
    if failure is not None:
        pytest.fail(f"{failure}; inspect owner-only capture at {capture.path}")
