"""Pure helpers for public-installer cold-start acceptance runs.

Holds the proof surfaces shared with ``installer_cold_start_proof`` (which owns
matrix and probe-script generation): the subprocess runner, the secret-marker
scan, the AWS identity preflight, and the fresh-install ``yoke status``
allowlist the generated probe embeds.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from yoke_core.domain.deploy_remote import aws_capability_env


SECRET_MARKERS: tuple[str, ...] = ("yoke_v1_", "ghu_", "ghs_", "ghr_")
DEFAULT_REGION = "us-east-1"
DEFAULT_AWS_PROJECT = "yoke"

# A fresh, not-yet-onboarded host has no machine config, no connections, and no
# active env, so ``yoke status --json`` exits non-zero reporting first-run
# config errors. These severity=="error" issue codes are EXPECTED on such a host
# and must not fail the cold-start probe; any other error code is a genuinely
# broken install. The public installer shim
# (``packaging/public-installer/install.py``) keeps its own literal copy because
# it is a dependency-free standalone download that cannot import yoke_core;
# ``test_installer_cold_start_proof`` asserts the two stay equal.
FRESH_STATUS_ERROR_CODES: tuple[str, ...] = (
    "config_missing",
    "schema_version",
    "connections_required",
    "active_env_required",
    "active_env",
    "temp_root_not_writable",
    "cache_dir_not_writable",
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    """Small subprocess runner so tests can assert argv/env without AWS calls."""

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: int = 60,
    ) -> CommandResult:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            env=dict(env) if env is not None else None,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


def scan_secret_markers(text: str) -> list[str]:
    return [marker for marker in SECRET_MARKERS if marker in text]


def scan_log_file(path: Path) -> list[str]:
    return scan_secret_markers(_redaction_scan_text(path))


def aws_identity_preflight(
    *,
    project: str = DEFAULT_AWS_PROJECT,
    region: str = DEFAULT_REGION,
    runner: CommandRunner | None = None,
) -> dict[str, object]:
    selected_runner = runner or CommandRunner()
    env = aws_capability_env(project, region)
    version = selected_runner.run(["aws", "--version"], env=env, timeout=30)
    if version.returncode != 0:
        raise RuntimeError(_format_command_failure("aws --version", version))

    identity = selected_runner.run(
        ["aws", "sts", "get-caller-identity", "--output", "json"],
        env=env,
        timeout=60,
    )
    if identity.returncode != 0:
        raise RuntimeError(
            _format_command_failure("aws sts get-caller-identity", identity)
        )
    try:
        payload = json.loads(identity.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("aws sts get-caller-identity returned invalid JSON") from exc
    return {
        "ok": True,
        "project": project,
        "region": region,
        "aws_cli": version.stdout.strip() or version.stderr.strip(),
        "account": str(payload.get("Account") or ""),
        "arn": str(payload.get("Arn") or ""),
        "user_id": str(payload.get("UserId") or ""),
    }


def _redaction_scan_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(payload, dict) and "secret_marker_denies" in payload:
        payload = dict(payload)
        payload["secret_marker_denies"] = []
        return json.dumps(payload, sort_keys=True)
    return text


def _format_command_failure(label: str, result: CommandResult) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    if detail:
        return f"{label} failed with exit {result.returncode}: {detail}"
    return f"{label} failed with exit {result.returncode}"
