"""Provider-specific environment and argv for Codex CLI turns."""

from __future__ import annotations

from yoke_contracts.session_control.launch_permission_bypass import (
    CODEX_EXEC_BYPASS_ARGUMENTS,
)
from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    native_model_selector,
)
from yoke_harness.session_relay_codex import CodexNativeRequest
from yoke_harness.session_relay_environment import native_session_environment


def codex_launch_environment(request: CodexNativeRequest) -> dict[str, str]:
    return native_session_environment(
        executor="codex",
        provider="openai",
        model=request.requested_model,
        markers={"CODEX_INTERNAL_ORIGINATOR_OVERRIDE": request.surface},
        launch_id=request.job_id if request.job_kind == "launch" else None,
        launch_attestation=request.launch_attestation,
    )


def codex_base_command(binary: str, request: CodexNativeRequest) -> list[str]:
    command = [
        binary,
        "exec",
        "--json",
        "--skip-git-repo-check",
        *CODEX_EXEC_BYPASS_ARGUMENTS,
    ]
    selection = LaunchModelSelection(
        request.requested_model,
        request.requested_reasoning_effort,
        request.requested_context_window_tokens,
    )
    model = native_model_selector("codex-cli", selection)
    if model:
        command.extend(["--model", model])
    if selection.reasoning_effort:
        command.extend(["-c", f"model_reasoning_effort={selection.reasoning_effort}"])
    return command


__all__ = ["codex_base_command", "codex_launch_environment"]
