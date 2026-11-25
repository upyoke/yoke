"""SYSTEM scripts on a native Windows lab: the only admin path QA has.

The lab's standard SSH user cannot change machine-wide state, so fixture
setup and undo run through the cloud provider's run-command as SYSTEM. Azure
is the one provider with that path today; a lab without it can apply no
fixture, so it has none to undo.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

from yoke_contracts.azure_admin import AzureAdminError
from yoke_contracts.azure_cli_prerequisite import AzureCliPrerequisiteError
from yoke_contracts.machine_fixture_verify import (
    RUNNER_UNAVAILABLE,
    MachineFixtureFailed,
)
from yoke_contracts.machine_qa_failures import HostControlLocalError


def _emit(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def run_system_script(material: Any, script: str, *, timeout: int) -> list[dict[str, Any]]:
    """Run one script as SYSTEM and return its verify records, or refuse by name."""
    from yoke_core.domain.cloud_machine_power import (
        machine_power,
        registered_power_project,
    )
    from yoke_core.domain.deploy_remote import CommandRunner

    settings = material.settings
    name = settings["resource_name"]
    if settings.get("cloud_provider") != "azure" or not settings.get("cloud_instance_id"):
        raise HostControlLocalError(
            code=RUNNER_UNAVAILABLE,
            phase="machine_fixture",
            detail=f"Test Machine {name} has no Azure run-command path for SYSTEM scripts.",
            recovery_hint=(
                "Machine fixtures need a lab registered with cloud_provider azure and its "
                "VM resource id; see the native Windows host provisioning guide."
            ),
        )
    project = registered_power_project(settings)
    try:
        with machine_power(project, settings, CommandRunner(), _emit) as provider:
            return provider.run_script(script, timeout)
    except (AzureAdminError, AzureCliPrerequisiteError) as exc:
        raise MachineFixtureFailed(
            records=[],
            detail=f"Test Machine {name}: {exc}",
            recovery_hint=f"Repair the named Azure access, then retry; check it with `yoke azure admin-status --project {project}`.",
        ) from exc


def project_public_key(material: Any) -> str:
    """The project key's public half, which the lab's authorized_keys hold."""
    key = material.secret_paths["ssh_private_key"]
    try:
        result = subprocess.run(
            ["ssh-keygen", "-y", "-f", key], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result = subprocess.CompletedProcess([], 1, "", type(exc).__name__)
    public = result.stdout.strip()
    if result.returncode or not public.startswith("ssh-"):
        raise HostControlLocalError(
            code="machine_fixture_public_key_unavailable",
            phase="machine_fixture",
            detail="ssh-keygen could not read the Test Machine's private key.",
            recovery_hint=(
                "Restore the key with `yoke test-machine secret set --test-machine "
                f"{material.settings['resource_name']} --key ssh_private_key --value-file KEY_FILE`, then retry."
            ),
        )
    return public


__all__ = ["project_public_key", "run_system_script"]
