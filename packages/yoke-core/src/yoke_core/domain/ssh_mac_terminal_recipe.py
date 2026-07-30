"""Execute bounded installer-campaign recipes through SSH host control."""

from __future__ import annotations

from pathlib import Path
import shlex
import time
from collections.abc import Callable
from typing import Any, Mapping, Sequence
from uuid import uuid4

from yoke_core.domain.host_control_executor import HostActionResult
from yoke_core.domain.machine_qa_operator_gate import (
    run_machine_browser_approval,
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
    capture_recipe_transcript,
    read_recipe_exit_code,
    recipe_assertion_failures,
    send_recipe_keys,
)
from yoke_core.domain.terminal_screenshot_quality import (
    TerminalScreenshotRegistry,
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
    progress_callback: Callable[[], None] | None,
    allowed_operator_urls: tuple[str, ...],
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
    screenshot_registry = TerminalScreenshotRegistry()
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
            operator_gate = action.get("operator_gate")
            if operator_gate == "machine_browser_approval":
                gate_result = run_machine_browser_approval(
                    run,
                    backend=backend,
                    session=session,
                    action=action,
                    progress_callback=progress_callback,
                    allowed_base_urls=allowed_operator_urls,
                )
                ready_transcript = gate_result.transcript
                if not gate_result.ok:
                    captures.append(
                        {
                            "key": str(action["step"]),
                            "reached": False,
                            "transcript": ready_transcript,
                            "operator_gate": operator_gate,
                        }
                    )
                    return HostActionResult(
                        False,
                        {
                            "steps": captures,
                            "terminal_backend": backend,
                            "operator_gate": operator_gate,
                        },
                        gate_result.error_code,
                    )
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
            if operator_gate is None and action["keys"] and not send_recipe_keys(
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
            if operator_gate is None and (
                action["keys"] or "wait_seconds" in action
            ):
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
                    window_id=terminal_window_id,
                )
                if screenshot is None:
                    degraded.append(f"{key}: screenshot capture blocked")
                else:
                    duplicate_of = screenshot_registry.duplicate_of(
                        key,
                        screenshot,
                    )
                    if duplicate_of is not None:
                        return HostActionResult(
                            False,
                            {
                                "steps": captures,
                                "terminal_backend": backend,
                                "duplicate_checkpoint": key,
                                "original_checkpoint": duplicate_of,
                            },
                            "terminal_duplicate_screenshot",
                        )
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


def execute_terminal_recipe(*args: Any, **kwargs: Any) -> HostActionResult:
    """Compatibility entrypoint for the split staging/dispatch owner."""
    from yoke_core.domain.ssh_mac_terminal_recipe_dispatch import (
        execute_terminal_recipe as execute,
    )

    return execute(*args, **kwargs)


__all__ = ["execute_terminal_recipe"]
