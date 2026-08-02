"""Execute user-visible recipes directly in macOS Terminal.app."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
import shlex
import time
from typing import Any
from uuid import uuid4

from yoke_core.domain.host_control_executor import HostActionResult
from yoke_core.domain.machine_qa_operator_gate import (
    run_machine_browser_approval_with_io,
)
from yoke_core.domain.ssh_mac_browser_approval import approve_machine_in_safari
from yoke_core.domain.qa_artifact_handle import local_handle
from yoke_core.domain.ssh_mac_terminal_app import (
    RunRemote,
    capture_terminal_app_screen,
    capture_terminal_app_transcript,
    close_terminal_app_window,
    open_terminal_app_window,
    send_terminal_app_keys,
)
from yoke_core.domain.ssh_mac_terminal_readiness import (
    DEFAULT_READY_TIMEOUT_SECONDS,
    wait_for_ready_text_with_reader,
)
from yoke_core.domain.ssh_mac_terminal_recipe_support import (
    read_recipe_exit_code,
    recipe_assertion_failures,
)
from yoke_core.domain.terminal_screenshot_quality import (
    TerminalScreenshotRegistry,
)


def _failure(
    error_code: str,
    *,
    captures: list[dict[str, Any]],
    **evidence: Any,
) -> HostActionResult:
    return HostActionResult(
        False,
        {
            "execution_mode": "terminal",
            "terminal_surface": "Terminal.app",
            "steps": captures,
            **evidence,
        },
        error_code,
    )


def run_terminal_app_recipe(
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
    """Run one recipe in the same Terminal.app surface a person operates."""
    session = "yoke-qa-" + uuid4().hex[:12]
    status_path = f"/tmp/{session}.exit"
    evidence_root = evidence_parent / session
    evidence_root.mkdir(parents=True, exist_ok=True)
    wrapped = (
        "printf '\\033c'; set +e; ( "
        + entry_surface
        + " ); rc=$?; printf '%s\\n' \"$rc\" > "
        + shlex.quote(status_path)
    )
    started = time.monotonic()
    captures: list[dict[str, Any]] = []
    degraded: list[str] = []
    reached: list[str] = []
    screenshot_registry = TerminalScreenshotRegistry()
    window_id: int | None = None
    try:
        window_id = open_terminal_app_window(
            run,
            command=wrapped,
            terminal_size=terminal_size,
        )
        if window_id is None:
            return _failure(
                "terminal_app_launch_failed",
                captures=captures,
                staged_files=staged,
            )

        def read_transcript() -> str:
            assert window_id is not None
            return capture_terminal_app_transcript(
                run,
                window_id=window_id,
            )

        def send_keys(keys: Sequence[str]) -> bool:
            assert window_id is not None
            return send_terminal_app_keys(
                run,
                window_id=window_id,
                keys=keys,
            )

        time.sleep(float(config["start_delay"]))
        for action in config["actions"]:
            if time.monotonic() - started > float(config["max_wall_seconds"]):
                return _failure(
                    "terminal_recipe_timed_out",
                    captures=captures,
                )
            ready_text = tuple(action.get("ready_text", ()))
            ready_transcript: str | None = None
            browser_evidence: dict[str, Any] | None = None
            operator_gate = action.get("operator_gate")
            if operator_gate == "machine_browser_approval":
                gate_result = run_machine_browser_approval_with_io(
                    read_transcript=read_transcript,
                    send_keys=send_keys,
                    action=action,
                    progress_callback=progress_callback,
                    allowed_base_urls=allowed_operator_urls,
                    approve_browser=lambda url, code: approve_machine_in_safari(
                        run,
                        verification_url=url,
                        user_code=code,
                    ),
                )
                ready_transcript = gate_result.transcript
                browser_evidence = gate_result.browser_evidence
                if not gate_result.ok:
                    captures.append(
                        {
                            "key": str(action["step"]),
                            "reached": False,
                            "transcript": ready_transcript,
                            "operator_gate": operator_gate,
                            "browser_approval": browser_evidence,
                        }
                    )
                    return _failure(
                        str(gate_result.error_code),
                        captures=captures,
                        operator_gate=operator_gate,
                        browser_approval=browser_evidence,
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
                ready, ready_transcript = wait_for_ready_text_with_reader(
                    read_transcript=read_transcript,
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
                    return _failure(
                        "terminal_action_not_ready",
                        captures=captures,
                        waiting_for=list(ready_text),
                    )
            if operator_gate is None and action["keys"]:
                if not send_keys(action["keys"]):
                    return _failure(
                        "terminal_app_input_failed",
                        captures=captures,
                    )
            if operator_gate is None and (action["keys"] or "wait_seconds" in action):
                time.sleep(float(action.get("wait_seconds", config["step_delay"])))
            key = str(action["step"])
            transcript = (
                ready_transcript
                if ready_transcript is not None and not action["keys"]
                else read_transcript()
            )
            capture = {
                "key": key,
                "reached": bool(transcript.strip()),
                "transcript": transcript,
            }
            if browser_evidence is not None:
                capture["browser_approval"] = browser_evidence
            captures.append(capture)
            reached.append(key)
            if action["capture"] and key in config["capture_checkpoints"]:
                assert window_id is not None
                screenshot = capture_terminal_app_screen(
                    run,
                    session=session,
                    key=f"{len(captures):03d}-{key}",
                    evidence_root=evidence_root,
                    window_id=window_id,
                )
                if screenshot is None:
                    degraded.append(f"{key}: screenshot capture blocked")
                else:
                    duplicate_of = screenshot_registry.duplicate_of(
                        key,
                        screenshot,
                    )
                    if duplicate_of is not None:
                        return _failure(
                            "terminal_duplicate_screenshot",
                            captures=captures,
                            duplicate_checkpoint=key,
                            original_checkpoint=duplicate_of,
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
            "terminal_surface": "Terminal.app",
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
        if window_id is not None:
            send_terminal_app_keys(
                run,
                window_id=window_id,
                keys=("C-c",),
            )
            time.sleep(0.2)
        close_terminal_app_window(run, window_id=window_id)
        run(f"rm -f {shlex.quote(status_path)}", timeout=10)


__all__ = ["run_terminal_app_recipe"]
