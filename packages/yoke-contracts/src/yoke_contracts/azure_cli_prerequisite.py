"""Read-only Azure CLI prerequisite shared by admin and cloud power calls."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

INSTALL_DOCS = "https://learn.microsoft.com/cli/azure/install-azure-cli"


@dataclass(frozen=True)
class AzureCli:
    command: tuple[str, ...]
    version: str


class AzureCliPrerequisiteError(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(
            f"{code}: {detail}; install or repair Azure CLI: {INSTALL_DOCS}; "
            "put az on PATH and verify with `az --version`"
        )


def check_azure_cli() -> AzureCli:
    executable = shutil.which("az")
    if executable is None:
        if platform.system() == "Windows":
            roots = [
                Path(os.environ.get(key, default))
                / "Microsoft SDKs/Azure/CLI2/wbin/az.cmd"
                for key, default in (
                    ("ProgramFiles", r"C:\Program Files"),
                    ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                )
            ]
        else:
            roots = [
                Path(p)
                for p in ("/opt/homebrew/bin/az", "/usr/local/bin/az", "/usr/bin/az")
            ]
        installed = next((path for path in roots if path.is_file()), None)
        raise AzureCliPrerequisiteError(
            "azure-cli-not-on-path" if installed else "azure-cli-missing",
            f"Azure CLI is installed at {installed} but not on PATH"
            if installed
            else "Azure CLI is not installed",
        )
    command = (executable,)
    if platform.system() == "Windows" and Path(executable).suffix.lower() in (
        ".cmd",
        ".bat",
    ):
        # The official MSI shim invokes this bundled interpreter. Bypass cmd.exe:
        # it reparses secret characters (&, %, quotes) even with shell=False.
        python = Path(executable).parent.parent / "python.exe"
        if not python.is_file():
            raise AzureCliPrerequisiteError(
                "azure-cli-unusable", "Azure CLI's bundled python.exe is missing"
            )
        command = (str(python), "-IBm", "azure.cli")
    try:
        result = subprocess.run(
            [*command, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AzureCliPrerequisiteError(
            "azure-cli-unusable", "az --version could not run"
        ) from exc
    if result.returncode:
        raise AzureCliPrerequisiteError("azure-cli-unusable", "az --version failed")
    return AzureCli(
        command,
        result.stdout.strip().splitlines()[0] if result.stdout.strip() else "",
    )
