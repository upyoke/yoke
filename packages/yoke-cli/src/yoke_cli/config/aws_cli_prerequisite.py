"""Read-only AWS CLI readiness for the operator's raw pass-through.

Yoke's caller-identity and VPS operations use boto3 in-process with credentials
from the machine-local ``aws-admin`` capability. ``yoke aws exec`` is the one
surface that deliberately hands arbitrary arguments to the AWS CLI, and
``yoke aws preflight`` lets an operator check that optional executable before
using the pass-through. Each refusal carries a named code and the recovery for
this operating system, including an install whose directory is missing from
``PATH``.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

#: The executable the raw ``yoke aws exec`` pass-through invokes.
AWS_CLI_EXECUTABLE = "aws"

#: Official install instructions, quoted on every refusal.
AWS_CLI_INSTALL_DOCS_URL = (
    "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
)

#: Longest a healthy ``aws --version`` takes; past this the binary is broken.
AWS_CLI_PROBE_TIMEOUT_SECONDS = 15.0

#: Install locations the official installers use, checked only to tell
#: "not installed" apart from "installed but not on PATH". Each is one
#: explicit candidate file, never a directory walk.
_KNOWN_UNIX_LOCATIONS = (
    "/usr/local/bin/aws",
    "/opt/homebrew/bin/aws",
    "/usr/bin/aws",
    "/snap/bin/aws",
    "~/.local/bin/aws",
)
_KNOWN_WINDOWS_LOCATIONS = (
    r"C:\Program Files\Amazon\AWSCLIV2\aws.exe",
    r"C:\Program Files (x86)\Amazon\AWSCLIV2\aws.exe",
)

_MACOS_INSTALL_COMMAND = (
    'curl "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o "AWSCLIV2.pkg" && '
    "sudo installer -pkg AWSCLIV2.pkg -target /"
)
_LINUX_INSTALL_COMMAND = (
    'curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" '
    '-o "awscliv2.zip" && unzip -q awscliv2.zip && sudo ./aws/install'
)
_WINDOWS_INSTALL_COMMAND = "msiexec.exe /i https://awscli.amazonaws.com/AWSCLIV2.msi"

_RUN = subprocess.run
_WHICH = shutil.which
_SYSTEM = platform.system


@dataclass(frozen=True)
class AwsCli:
    """A successful, read-only AWS CLI preflight receipt."""

    executable: str
    version: str


class AwsCliPrerequisiteError(RuntimeError):
    """A diagnosed AWS CLI refusal with person-shaped recovery."""

    def __init__(self, code: str, message: str, detail_lines: Sequence[str]) -> None:
        super().__init__(message)
        self.code = code
        self.detail_lines = tuple(detail_lines)

    def report_lines(self) -> tuple[str, ...]:
        """The refusal as a terminal prints it: reason first, then recovery."""
        return (f"error: {self}", *(f"  {line}" for line in self.detail_lines))


def check_aws_cli() -> AwsCli:
    """Require an AWS CLI this machine can actually run.

    Raises :class:`AwsCliPrerequisiteError` naming which of the three failures
    happened: not installed, installed off ``PATH``, or present but unusable.
    """
    executable = _WHICH(AWS_CLI_EXECUTABLE)
    if not executable:
        _raise_not_on_path()
    return _probe_version(executable)


def _raise_not_on_path() -> None:
    """Refuse, distinguishing a missing install from a missing ``PATH`` entry."""
    installed = _first_known_location()
    if installed is not None:
        raise AwsCliPrerequisiteError(
            "aws-cli-not-on-path",
            f"The AWS CLI is installed at {installed}, but its folder is not "
            "on this shell's PATH.",
            (
                f'Add it to PATH: export PATH="{installed.parent}:$PATH"',
                "Add the same line to your shell profile so new shells keep it.",
                f"Verify with: {AWS_CLI_EXECUTABLE} --version",
            ),
        )
    raise AwsCliPrerequisiteError(
        "aws-cli-missing",
        "The AWS CLI is not installed on this machine.",
        (
            f"Install it: {_install_command(_SYSTEM())}",
            f"Full instructions: {AWS_CLI_INSTALL_DOCS_URL}",
            f"Verify with: {AWS_CLI_EXECUTABLE} --version",
        ),
    )


def _probe_version(executable: str) -> AwsCli:
    """Run ``aws --version`` so a broken install fails here, not mid-deploy."""
    try:
        result = _RUN(
            (executable, "--version"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=AWS_CLI_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AwsCliPrerequisiteError(
            "aws-cli-unusable",
            f"The AWS CLI at {executable} could not be run.",
            (
                f"It reported: {_diagnostic(str(exc))}",
                f"Reinstall it: {_install_command(_SYSTEM())}",
                f"Full instructions: {AWS_CLI_INSTALL_DOCS_URL}",
            ),
        ) from exc
    if result.returncode != 0:
        raise AwsCliPrerequisiteError(
            "aws-cli-unusable",
            f"The AWS CLI at {executable} exited {result.returncode} on "
            "`aws --version`.",
            (
                f"It reported: {_diagnostic(result.stdout)}",
                f"Reinstall it: {_install_command(_SYSTEM())}",
                f"Full instructions: {AWS_CLI_INSTALL_DOCS_URL}",
            ),
        )
    return AwsCli(executable=executable, version=_diagnostic(result.stdout))


def _first_known_location() -> Path | None:
    """The first official install location holding an executable, if any."""
    windows = _SYSTEM().lower() == "windows"
    candidates = _KNOWN_WINDOWS_LOCATIONS if windows else _KNOWN_UNIX_LOCATIONS
    for candidate in candidates:
        path = Path(candidate).expanduser()
        try:
            if path.is_file() and (windows or os.access(path, os.X_OK)):
                return path
        except OSError:
            continue
    return None


def _install_command(system_name: str) -> str:
    system = system_name.lower()
    if system == "darwin":
        return _MACOS_INSTALL_COMMAND
    if system == "windows":
        return _WINDOWS_INSTALL_COMMAND
    if system == "linux":
        return _LINUX_INSTALL_COMMAND
    return AWS_CLI_INSTALL_DOCS_URL


def _diagnostic(value: str | None) -> str:
    text = (value or "").strip()
    printable = "".join(char if char.isprintable() else " " for char in text)
    return printable[:512]


__all__ = [
    "AWS_CLI_EXECUTABLE",
    "AWS_CLI_INSTALL_DOCS_URL",
    "AWS_CLI_PROBE_TIMEOUT_SECONDS",
    "AwsCli",
    "AwsCliPrerequisiteError",
    "check_aws_cli",
]
