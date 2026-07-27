"""Shared recipe builders and doubles for terminal-recipe tests."""

from __future__ import annotations

import subprocess

from yoke_core.domain.host_control_executor import HostActionResult


def completed(
    command: str,
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def recipe(
    *,
    mode: str = "ssh-command",
    stage_files: list[dict[str, str]] | None = None,
    expected_return_codes: list[int] | None = None,
) -> dict[str, object]:
    return {
        "actions": [
            {
                "step": "done",
                "keys": [],
                "capture": False,
            }
        ],
        "capture_checkpoints": [],
        "execution_mode": mode,
        "expected_return_codes": expected_return_codes or [0],
        "expected_text": ["ready"],
        "max_wall_seconds": 30.0,
        "notes": "Exercise one bounded terminal recipe.",
        "post_checks": ["secret_free"],
        "post_state_assertions": [],
        "setup_operations": [],
        "stage_files": stage_files or [],
        "start_delay": 0.0,
        "step_delay": 0.0,
    }


class SecretRecipeControl:
    home = "/Users/tester"
    shell = "/bin/zsh"
    xdg_bin_home = None

    def run_terminal_recipe(self, **_kwargs: object) -> HostActionResult:
        return HostActionResult(
            True,
            {
                "steps": [
                    {
                        "key": "done",
                        "transcript": "credential=top-secret",
                    }
                ]
            },
        )


__all__ = ["SecretRecipeControl", "completed", "recipe"]
