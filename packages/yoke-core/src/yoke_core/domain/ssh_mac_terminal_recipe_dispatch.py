"""Staging and mode dispatch for bounded terminal recipes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from yoke_core.domain.host_control_executor import HostActionResult
from yoke_core.domain.machine_qa_result_safety import redact_machine_qa_value
from yoke_core.domain.ssh_mac_terminal_capture import RunRemote
from yoke_core.domain.ssh_mac_terminal_recipe_cleanup import (
    remove_staged_files,
    with_staged_cleanup,
)
from yoke_core.domain.ssh_mac_terminal_recipe_support import (
    UploadBytes,
    run_command_recipe,
    stage_recipe_files,
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
    progress_callback: Callable[[], None] | None = None,
    allowed_operator_urls: tuple[str, ...] = (),
) -> HostActionResult:
    """Execute one already-validated campaign recipe and return raw evidence."""
    staged_ok, staged, staged_secrets = stage_recipe_files(
        config["stage_files"],
        upload_bytes=upload_bytes,
    )
    if not staged_ok:
        failed = HostActionResult(
            False,
            {"staged_files": staged},
            "terminal_stage_file_failed",
        )
        return with_staged_cleanup(run, failed, staged)
    all_secrets = tuple(secret_values) + staged_secrets
    try:
        mode = config["execution_mode"]
        if mode == "ssh-command":
            result = run_command_recipe(
                run,
                entry_surface=entry_surface,
                config=config,
                staged=staged,
                secret_values=all_secrets,
            )
        elif mode == "terminal":
            from yoke_core.domain.ssh_mac_terminal_app_recipe import (
                run_terminal_app_recipe,
            )

            result = run_terminal_app_recipe(
                run,
                entry_surface=entry_surface,
                required_completion=required_completion,
                config=config,
                evidence_parent=evidence_parent,
                secret_values=all_secrets,
                staged=staged,
                terminal_size=terminal_size,
                progress_callback=progress_callback,
                allowed_operator_urls=allowed_operator_urls,
            )
        else:
            from yoke_core.domain.ssh_mac_terminal_recipe import (
                _run_interactive_recipe,
            )

            result = _run_interactive_recipe(
                run,
                entry_surface=entry_surface,
                required_completion=required_completion,
                config=config,
                evidence_parent=evidence_parent,
                secret_values=all_secrets,
                staged=staged,
                terminal_size=terminal_size,
                progress_callback=progress_callback,
                allowed_operator_urls=allowed_operator_urls,
            )
    except Exception:
        remove_staged_files(run, staged)
        raise
    safe_result = HostActionResult(
        result.ok,
        redact_machine_qa_value(result.evidence, all_secrets),
        result.error_code,
    )
    return with_staged_cleanup(run, safe_result, staged)


__all__ = ["execute_terminal_recipe"]
