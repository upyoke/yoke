"""Legacy step/expect execution on the registered SSH macOS host adapter."""

from __future__ import annotations

from pathlib import Path
import shlex
from typing import Any, Mapping, Sequence
from uuid import uuid4

from yoke_core.domain.host_control_executor import HostActionResult
from yoke_core.domain.qa_artifact_handle import local_handle
from yoke_core.domain.ssh_mac_terminal_capture import (
    RunRemote,
    capture_screen,
    close_terminal_session,
    close_terminal_window,
    detect_terminal_backend,
    open_terminal_window,
    send_terminal_input,
    wait_for_text,
)


def execute_legacy_terminal_case(
    run: RunRemote,
    *,
    entry_surface: str,
    required_completion: str,
    steps: Sequence[Mapping[str, Any]],
    capture_checkpoints: Sequence[str],
    evidence_parent: Path,
) -> HostActionResult:
    """Execute the pre-campaign step/expect shape without host-side secrets."""
    session = "yoke-qa-" + uuid4().hex[:12]
    backend = detect_terminal_backend(run)
    if backend is None:
        return HostActionResult(
            False,
            {
                "entry_surface_started": False,
                "terminal_backend": None,
            },
            "terminal_bridge_unavailable",
        )
    evidence_root = evidence_parent / session
    evidence_root.mkdir(parents=True, exist_ok=True)
    captured: list[dict[str, Any]] = []
    matched: list[str] = []
    degraded: list[str] = []
    terminal_window_id: int | None = None
    try:
        if backend == "tmux":
            start = f"tmux new-session -d -s {shlex.quote(session)} " + shlex.quote(
                entry_surface
            )
        else:
            start = f"screen -dmS {shlex.quote(session)} /bin/sh -lc " + shlex.quote(
                entry_surface
            )
        if run(start).returncode:
            return HostActionResult(
                False,
                {
                    "entry_surface_started": False,
                    "terminal_backend": backend,
                },
                "terminal_entry_failed",
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
                {
                    "entry_surface_started": True,
                    "terminal_attached": False,
                    "terminal_backend": backend,
                },
                "terminal_attach_failed",
            )
        for step in steps:
            sent = str(step.get("send") or "")
            if sent and not send_terminal_input(
                run,
                backend=backend,
                session=session,
                text=sent,
            ):
                return HostActionResult(
                    False,
                    {
                        "steps": captured,
                        "terminal_backend": backend,
                    },
                    "terminal_input_failed",
                )
            transcript = wait_for_text(
                run,
                backend=backend,
                session=session,
                expected=str(step["expect"]),
                timeout_seconds=int(step.get("timeout_seconds", 30)),
            )
            key = str(step["key"])
            reached = transcript is not None
            captured.append(
                {
                    "key": key,
                    "expect": str(step["expect"]),
                    "reached": reached,
                    "transcript": transcript or "",
                }
            )
            if not reached:
                return HostActionResult(
                    False,
                    {"steps": captured},
                    (
                        "terminal_completion_not_reached"
                        if key == required_completion
                        else "terminal_checkpoint_failed"
                    ),
                )
            matched.append(key)
            if key in capture_checkpoints:
                screenshot = capture_screen(
                    run,
                    session=session,
                    key=key,
                    evidence_root=evidence_root,
                )
                if screenshot is None:
                    degraded.append(f"{key}: screenshot capture blocked")
                else:
                    captured[-1]["artifact_handle"] = local_handle(
                        str(screenshot.resolve()),
                        "image/png",
                    )
        if required_completion not in matched:
            return HostActionResult(
                False,
                {
                    "steps": captured,
                    "required_completion": required_completion,
                },
                "terminal_completion_not_reached",
            )
        return HostActionResult(
            True,
            {
                "steps": captured,
                "required_completion": required_completion,
                "terminal_backend": backend,
                "capture_degraded_reason": "; ".join(degraded) or None,
            },
        )
    finally:
        close_terminal_session(
            run,
            backend=backend,
            session=session,
        )
        close_terminal_window(run, window_id=terminal_window_id)


__all__ = ["execute_legacy_terminal_case"]
