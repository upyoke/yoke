"""Execute bounded installer-campaign recipes through SSH host control."""

from __future__ import annotations

from pathlib import Path
import shlex
import time
from typing import Any, Mapping, Sequence
from uuid import uuid4

from yoke_core.domain.host_control_executor import HostActionResult
from yoke_core.domain.machine_qa_result_safety import (
    redact_machine_qa_value,
)
from yoke_core.domain.qa_artifact_handle import local_handle
from yoke_core.domain.ssh_mac_terminal_capture import (
    RunRemote,
    capture_screen,
    close_terminal_session,
    close_terminal_window,
    detect_terminal_backend,
    open_terminal_window,
    resize_terminal_session,
)
from yoke_core.domain.ssh_mac_terminal_readiness import (
    DEFAULT_READY_TIMEOUT_SECONDS,
    wait_for_ready_text,
)
from yoke_core.domain.ssh_mac_terminal_recipe_support import (
    UploadBytes,
    capture_recipe_transcript,
    cleanup_staged_files,
    read_recipe_exit_code,
    recipe_assertion_failures,
    run_command_recipe,
    send_recipe_keys,
    stage_recipe_files,
)


def _run_interactive_recipe(
    run: RunRemote,
    *,
    entry_surface: str,
    required_completion: str,
    config: Mapping[str, Any],
    evidence_parent: Path,
    secret_values: Sequence[str],
    staged: list[dict[str, str]],
    terminal_size: tuple[int, int] | None,
) -> HostActionResult:
    """Run one interactive recipe after its files are staged."""
    backend = detect_terminal_backend(run)
    if backend is None:
        return HostActionResult(
            False,
            {"terminal_backend": None, "staged_files": staged},
            "terminal_bridge_unavailable",
        )
    session = "yoke-qa-" + uuid4().hex[:12]
    status_path = f"/tmp/{session}.exit"
    evidence_root = evidence_parent / session
    evidence_root.mkdir(parents=True, exist_ok=True)
    wrapped = (
        "set +e; ( "
        + entry_surface
        + " ); rc=$?; printf '%s\\n' \"$rc\" > "
        + shlex.quote(status_path)
        + "; sleep 600"
    )
    start = (
        f"tmux new-session -d -s {shlex.quote(session)} /bin/sh -lc "
        + shlex.quote(wrapped)
        if backend == "tmux"
        else f"screen -dmS {shlex.quote(session)} /bin/sh -lc " + shlex.quote(wrapped)
    )
    started = time.monotonic()
    captures: list[dict[str, Any]] = []
    degraded: list[str] = []
    reached: list[str] = []
    terminal_window_id: int | None = None
    try:
        if run(start, timeout=20).returncode:
            return HostActionResult(
                False,
                {"terminal_backend": backend, "staged_files": staged},
                "terminal_entry_failed",
            )
        if terminal_size is not None and not resize_terminal_session(
            run,
            backend=backend,
            session=session,
            columns=terminal_size[0],
            rows=terminal_size[1],
        ):
            return HostActionResult(
                False,
                {"terminal_backend": backend, "staged_files": staged},
                "terminal_resize_failed",
            )
        attach = (
            f"tmux attach-session -t {session}"
            if backend == "tmux"
            else f"screen -r {session}"
        )
        terminal_window_id = open_terminal_window(
            run,
            command=attach,
        )
        if terminal_window_id is None:
            return HostActionResult(
                False,
                {"terminal_backend": backend, "staged_files": staged},
                "terminal_attach_failed",
            )
        time.sleep(float(config["start_delay"]))
        for action in config["actions"]:
            if time.monotonic() - started > float(config["max_wall_seconds"]):
                return HostActionResult(
                    False,
                    {"steps": captures, "terminal_backend": backend},
                    "terminal_recipe_timed_out",
                )
            ready_text = tuple(action.get("ready_text", ()))
            ready_transcript: str | None = None
            if ready_text:
                remaining_wall_seconds = max(
                    0.0,
                    float(config["max_wall_seconds"]) - (time.monotonic() - started),
                )
                ready_timeout_seconds = min(
                    float(
                        action.get(
                            "ready_timeout_seconds",
                            DEFAULT_READY_TIMEOUT_SECONDS,
                        )
                    ),
                    remaining_wall_seconds,
                )
                ready, ready_transcript = wait_for_ready_text(
                    run,
                    backend=backend,
                    session=session,
                    expected=ready_text,
                    timeout_seconds=ready_timeout_seconds,
                )
                if not ready:
                    captures.append(
                        {
                            "key": str(action["step"]),
                            "reached": False,
                            "transcript": ready_transcript,
                            "waiting_for": list(ready_text),
                        }
                    )
                    return HostActionResult(
                        False,
                        {
                            "steps": captures,
                            "terminal_backend": backend,
                            "waiting_for": list(ready_text),
                        },
                        "terminal_action_not_ready",
                    )
            if action["keys"] and not send_recipe_keys(
                run,
                backend=backend,
                session=session,
                keys=action["keys"],
            ):
                return HostActionResult(
                    False,
                    {"steps": captures, "terminal_backend": backend},
                    "terminal_input_failed",
                )
            if action["keys"] or "wait_seconds" in action:
                time.sleep(float(action.get("wait_seconds", config["step_delay"])))
            key = str(action["step"])
            transcript = (
                ready_transcript
                if ready_transcript is not None and not action["keys"]
                else capture_recipe_transcript(
                    run,
                    backend=backend,
                    session=session,
                )
            )
            capture = {
                "key": key,
                "reached": bool(transcript.strip()),
                "transcript": transcript,
            }
            captures.append(capture)
            reached.append(key)
            if action["capture"] and key in config["capture_checkpoints"]:
                screenshot = capture_screen(
                    run,
                    session=session,
                    key=f"{len(captures):03d}-{key}",
                    evidence_root=evidence_root,
                )
                if screenshot is None:
                    degraded.append(f"{key}: screenshot capture blocked")
                else:
                    capture["artifact_handle"] = local_handle(
                        str(screenshot.resolve()),
                        "image/png",
                    )
        combined = "\n".join(str(capture["transcript"]) for capture in captures)
        exit_code = read_recipe_exit_code(run, status_path=status_path)
        failures = recipe_assertion_failures(
            combined,
            expected_text=config["expected_text"],
            post_checks=config["post_checks"],
            secret_values=secret_values,
            terminal_exit_code=exit_code,
        )
        if exit_code is not None and exit_code not in set(
            config["expected_return_codes"]
        ):
            failures.append(f"return code {exit_code} not in expected set")
        if required_completion not in reached:
            failures.append("required completion was not reached")
        evidence = {
            "execution_mode": "terminal",
            "terminal_backend": backend,
            "staged_files": staged,
            "steps": captures,
            "required_completion": required_completion,
            "exit_code": exit_code,
            "assertion_failures": failures,
            "capture_degraded_reason": "; ".join(degraded) or None,
        }
        return HostActionResult(
            not failures,
            evidence,
            None if not failures else "terminal_recipe_assertion_failed",
        )
    finally:
        close_terminal_session(
            run,
            backend=backend,
            session=session,
        )
        close_terminal_window(run, window_id=terminal_window_id)
        run(f"rm -f {shlex.quote(status_path)}", timeout=10)


def _with_staged_cleanup(
    run: RunRemote,
    result: HostActionResult,
    staged: list[dict[str, str]],
) -> HostActionResult:
    if not staged:
        return result
    try:
        cleanup_ok = cleanup_staged_files(run, staged)
    except Exception:
        cleanup_ok = False
    evidence = {
        **result.evidence,
        "staged_file_cleanup": cleanup_ok,
    }
    if cleanup_ok:
        return HostActionResult(
            result.ok,
            evidence,
            result.error_code,
        )
    if result.error_code is not None:
        evidence["primary_error_code"] = result.error_code
    return HostActionResult(
        False,
        evidence,
        "terminal_stage_file_cleanup_failed",
    )


def execute_terminal_recipe(
    run: RunRemote,
    *,
    upload_bytes: UploadBytes,
    entry_surface: str,
    required_completion: str,
    config: Mapping[str, Any],
    evidence_parent: Path,
    secret_values: Sequence[str],
    terminal_size: tuple[int, int] | None = None,
) -> HostActionResult:
    """Execute one already-validated campaign recipe and return raw evidence."""
    staged_ok, staged, staged_secrets = stage_recipe_files(
        config["stage_files"],
        upload_bytes=upload_bytes,
    )
    if not staged_ok:
        return _with_staged_cleanup(
            run,
            HostActionResult(
                False,
                {"staged_files": staged},
                "terminal_stage_file_failed",
            ),
            staged,
        )
    all_secrets = tuple(secret_values) + staged_secrets
    try:
        if config["execution_mode"] == "ssh-command":
            result = run_command_recipe(
                run,
                entry_surface=entry_surface,
                config=config,
                staged=staged,
                secret_values=all_secrets,
            )
        else:
            result = _run_interactive_recipe(
                run,
                entry_surface=entry_surface,
                required_completion=required_completion,
                config=config,
                evidence_parent=evidence_parent,
                secret_values=all_secrets,
                staged=staged,
                terminal_size=terminal_size,
            )
    except Exception:
        cleanup_staged_files(run, staged)
        raise
    result = HostActionResult(
        result.ok,
        redact_machine_qa_value(result.evidence, all_secrets),
        result.error_code,
    )
    return _with_staged_cleanup(run, result, staged)


__all__ = ["execute_terminal_recipe"]
