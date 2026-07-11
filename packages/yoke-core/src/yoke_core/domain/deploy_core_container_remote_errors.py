"""Shared failure types and formatting for core-container remote steps."""

from __future__ import annotations

from yoke_core.domain.deploy_remote import CommandResult


class RemoteConvergenceError(RuntimeError):
    """A box-convergence step failed; message carries remediation."""


def fail_remote_step(
    step: str,
    result: CommandResult,
    remediation: str = "",
) -> None:
    """Raise a consistently formatted remote convergence failure."""
    detail = "\n".join(
        part for part in (result.stdout.strip(), result.stderr.strip()) if part
    )
    message = f"[core-deploy] {step} failed (rc={result.returncode})"
    if detail:
        message += f": {detail[-800:]}"
    if remediation:
        message += f"\n  remediation: {remediation}"
    raise RemoteConvergenceError(message)
