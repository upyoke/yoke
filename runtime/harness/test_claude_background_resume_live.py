"""Opt-in live probe for resuming a stopped Claude background session.

Run only when a disposable native Claude session is acceptable::

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
from typing import Callable
from uuid import UUID, uuid4

import pytest

from yoke_harness import session_relay_claude_process as process_module
from yoke_harness.session_relay_claude import (
    CLAUDE_NATIVE_TIMEOUT_SECONDS,
    ClaudeNativeInvocation,
    discover_claude_cli,
    lookup_claude_session,
    run_claude_process,
)
from yoke_harness.session_relay_claude_identity import (
    background_agent_id,
    resolve_background_session,
)
from yoke_harness.session_relay_claude_process import (
    ClaudeProcessResult,
    run_bounded_claude_process,
)
from yoke_harness.session_relay_environment import native_session_environment


_LIVE_OPT_IN = "I_ACCEPT_DISPOSABLE_SESSION"
_LIVE_OPT_IN_ENV = "YOKE_RUN_LIVE_CLAUDE_BACKGROUND_RESUME"
_REQUIRED_VERSION = "2.1.241"
_VERSION_PATTERN = re.compile(r"(?<![0-9.])2\.1\.241(?![0-9.])")
_LAUNCH_INSTRUCTION = (
    "Disposable Yoke resume probe. Reply READY and stop. "
    "Do not use tools or modify files."
)
_RESUME_INSTRUCTION = (
    "Disposable Yoke resume probe. Reply RESUMED and stop. "
    "Do not use tools or modify files."
)


class _ProbeFailure(RuntimeError):
    """A failure whose text is safe for the public pytest report."""


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

    def append(
        self,
        label: str,
        stdout,
        stderr,
        *,
        result: ClaudeProcessResult | None,
        exception: BaseException | None,
    ) -> None:
        stdout.seek(0, os.SEEK_END)
        stderr.seek(0, os.SEEK_END)
        stdout_bytes = stdout.tell()
        stderr_bytes = stderr.tell()
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
    call: Callable[[], ClaudeProcessResult],
) -> ClaudeProcessResult:
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
                capture.append(
                    label,
                    stdout_spool,
                    stderr_spool,
                    result=result,
                    exception=exception,
                )


def _safe_summary(
    capture: _PrivateNativeCapture,
    **outcome: object,
) -> str:
    return json.dumps(
        {
            "capture_path": str(capture.path),
            "capture_mode": oct(capture.path.stat().st_mode & 0o777),
            "surface": "claude-cli",
            "required_version": _REQUIRED_VERSION,
            "steps": capture.steps,
            **outcome,
        },
        sort_keys=True,
    )


def _isolated_roots() -> tuple[Path, Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="yoke-claude-resume-project-")).resolve()
    os.chmod(root, 0o700)
    project = root / "project"
    config = root / "config"
    project.mkdir(mode=0o700)
    config.mkdir(mode=0o700)
    return root, project, config


def _remove_isolated_root(root: Path) -> bool:
    temp_parent = Path(tempfile.gettempdir()).resolve()
    if (
        root.is_symlink()
        or root.parent != temp_parent
        or not root.name.startswith("yoke-claude-resume-project-")
    ):
        return False
    try:
        shutil.rmtree(root)
    except OSError:
        return False
    return not root.exists()


@pytest.mark.skipif(
    os.environ.get(_LIVE_OPT_IN_ENV) != _LIVE_OPT_IN,
    reason=f"set {_LIVE_OPT_IN_ENV}={_LIVE_OPT_IN} to create a disposable session",
)
def test_stopped_claude_background_session_accepts_production_resume_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = discover_claude_cli()
    if executable is None:
        raise _ProbeFailure("Claude CLI is unavailable")
    temp_root, cwd, config_root = _isolated_roots()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_root))
    hook_sources_absent = not (cwd / ".claude").exists() and not any(
        config_root.iterdir()
    )
    if not hook_sources_absent:
        _remove_isolated_root(temp_root)
        raise _ProbeFailure("isolated Claude hook sources are not empty")
    native_environment = native_session_environment(
        executor="claude-code",
        executor_version=_REQUIRED_VERSION,
        provider="anthropic",
        markers={"CLAUDE_CODE_ENTRYPOINT": "cli"},
    )

    def native(*argv: str) -> ClaudeProcessResult:
        return run_bounded_claude_process(
            argv,
            cwd=cwd,
            environment=native_environment,
            timeout_seconds=CLAUDE_NATIVE_TIMEOUT_SECONDS,
        )

    capture = _PrivateNativeCapture()
    print(f"CLAUDE_RESUME_PRIVATE_CAPTURE={capture.path}")
    short_id = None
    identity_resolved = False
    resume_succeeded = False
    cleanup_completed = False
    temp_root_removed = False
    failure: _ProbeFailure | None = None
    try:
        version = _recorded_call(
            capture,
            "version",
            lambda: native(executable, "--version"),
        )
        if version.returncode or not _VERSION_PATTERN.search(
            f"{version.stdout}\n{version.stderr}"
        ):
            raise _ProbeFailure("installed Claude CLI is not exact version 2.1.241")

        requested_id = str(uuid4())
        launch = ClaudeNativeInvocation(
            executable,
            cwd,
            requested_id,
            _REQUIRED_VERSION,
            _LAUNCH_INSTRUCTION,
        )
        launched = _recorded_call(
            capture,
            "launch",
            lambda: run_claude_process(launch),
        )
        if launched.returncode:
            raise _ProbeFailure("Claude background launch exited nonzero")
        short_id = background_agent_id(launched)
        if short_id is None:
            raise _ProbeFailure("Claude background launch identity was not parseable")

        lookup_count = 0

        def lookup() -> ClaudeProcessResult:
            nonlocal lookup_count
            lookup_count += 1
            return _recorded_call(
                capture,
                f"identity_lookup_{lookup_count}",
                lambda: lookup_claude_session(launch),
            )

        resolution = resolve_background_session(short_id, lookup)
        if resolution.session_id is None:
            raise _ProbeFailure("Claude background session identity did not resolve")
        actual_id = str(UUID(resolution.session_id))
        identity_resolved = True

        stopped = _recorded_call(
            capture,
            "stop_before_resume",
            lambda: native(executable, "stop", short_id),
        )
        if stopped.returncode:
            raise _ProbeFailure("Claude background session did not stop cleanly")

        resume = ClaudeNativeInvocation(
            executable,
            cwd,
            actual_id,
            _REQUIRED_VERSION,
            _RESUME_INSTRUCTION,
            resume=True,
        )
        resumed = _recorded_call(
            capture,
            "production_resume",
            lambda: run_claude_process(resume),
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
            stop_result = _recorded_call(
                capture,
                "cleanup_stop",
                lambda: native(executable, "stop", short_id),
            )
            remove_result = _recorded_call(
                capture,
                "cleanup_remove",
                lambda: native(executable, "rm", short_id),
            )
            cleanup_completed = remove_result.returncode == 0
            if stop_result.returncode and not cleanup_completed and failure is None:
                failure = _ProbeFailure("Claude background cleanup failed")
        temp_root_removed = _remove_isolated_root(temp_root)
        if not temp_root_removed and failure is None:
            failure = _ProbeFailure("isolated Claude temp root cleanup failed")
        capture.close()
        print(
            "CLAUDE_RESUME_REDACTED_SUMMARY="
            + _safe_summary(
                capture,
                identity_resolved=identity_resolved,
                resume_succeeded=resume_succeeded,
                cleanup_completed=cleanup_completed,
                hook_sources_absent_at_launch=hook_sources_absent,
                temp_root_removed=temp_root_removed,
            )
        )
    if failure is not None:
        pytest.fail(f"{failure}; inspect owner-only capture at {capture.path}")
