"""Deliberately advance a self-host CLI and its pinned server as one pair."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from yoke_cli.config import onboard_self_host_server
from yoke_cli.self_host import bundle
from yoke_cli.self_host import protection
from yoke_cli.self_host import release_target
from yoke_contracts.self_host_bootstrap_output import redact_api_tokens

INSTALL_TIMEOUT_SECONDS = 600.0
COMPOSE_TIMEOUT_SECONDS = 300.0

_RUN = subprocess.run
_CHECK_DOCKER = onboard_self_host_server.check_docker_prerequisites


class SelfHostUpgradeError(RuntimeError):
    """A safe, staged upgrade failure with an exact recovery."""

    def __init__(self, code: str, message: str, detail_lines: Sequence[str]) -> None:
        super().__init__(redact_api_tokens(message))
        self.code = code
        self.detail_lines = tuple(redact_api_tokens(line) for line in detail_lines)


@dataclass(frozen=True)
class UpgradePlan:
    """One read-only preview binding the release, bundle, and Docker binary."""

    directory: Path
    target: release_target.ReleaseTarget
    docker_executable: str
    previous_image: str

    @property
    def steps(self) -> tuple[str, ...]:
        return (
            f"install Yoke CLI {self.target.version} from {self.target.channel}",
            f"replace YOKE_SERVER_IMAGE with {self.target.image}",
            "run docker compose pull core",
            "run docker compose up -d",
        )


def plan_upgrade(
    *, directory: str | None = None, channel: str | None = None
) -> UpgradePlan:
    """Resolve and validate the complete plan without changing machine state."""
    try:
        target_dir = bundle.validate_existing_bundle(directory=directory)
        target = release_target.channel_release_target(channel=channel)
        prerequisites = _CHECK_DOCKER()
        previous_image = _read_server_image(target_dir / bundle.ENV_FILE_NAME)
    except bundle.SelfHostBundleError as exc:
        raise SelfHostUpgradeError(
            "bundle-invalid",
            "The self-host bundle is not safe to upgrade.",
            (str(exc), "Repair the named bundle path, then retry the upgrade."),
        ) from exc
    except release_target.ReleaseTargetError as exc:
        raise SelfHostUpgradeError(
            "release-target",
            "The paired Yoke release could not be resolved.",
            (str(exc), "Restore distribution access, then retry the upgrade."),
        ) from exc
    except onboard_self_host_server.SelfHostSetupError as exc:
        raise SelfHostUpgradeError(exc.code, str(exc), exc.detail_lines) from exc
    return UpgradePlan(
        directory=target_dir,
        target=target,
        docker_executable=prerequisites.executable,
        previous_image=previous_image,
    )


def execute_upgrade(plan: UpgradePlan) -> dict[str, Any]:
    """Execute a consented plan in CLI → pin → pull → restart order."""
    installer = _fetch_installer(plan)
    _install_cli(plan, installer)
    _replace_server_image(plan)
    _run_compose_step(plan, ("pull", "core"), code="compose-pull")
    _run_compose_step(plan, ("up", "-d"), code="compose-up")
    return {
        "ok": True,
        "directory": str(plan.directory),
        "channel": plan.target.channel,
        "version": plan.target.version,
        "source_commit": plan.target.source_commit,
        "previous_image": plan.previous_image,
        "image": plan.target.image,
        "steps": list(plan.steps),
    }


def _fetch_installer(plan: UpgradePlan) -> bytes:
    try:
        return release_target.fetch_installer(plan.target)
    except release_target.ReleaseTargetError as exc:
        raise SelfHostUpgradeError(
            "installer-fetch",
            "The paired CLI installer could not be fetched; nothing changed.",
            (str(exc), _retry_command(plan)),
        ) from exc


def _install_cli(plan: UpgradePlan, installer: bytes) -> None:
    path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix="yoke-self-host-upgrade-", suffix=".py", delete=False
        ) as handle:
            handle.write(installer)
            path = handle.name
        command = (
            sys.executable,
            path,
            "--version",
            plan.target.version,
            "--yes",
            "--no-onboard",
            "--base-url",
            plan.target.base_url,
        )
        completed = _run_capture(command, timeout=INSTALL_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SelfHostUpgradeError(
            "cli-install",
            "The CLI installer could not complete; the bundle pin was not changed.",
            (_diagnostic(str(exc)), _retry_command(plan)),
        ) from exc
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
    if completed.returncode != 0:
        raise SelfHostUpgradeError(
            "cli-install",
            "The CLI installer failed; the bundle pin was not changed.",
            (_completed_diagnostic(completed), _retry_command(plan)),
        )


def _replace_server_image(plan: UpgradePlan) -> None:
    env_path = plan.directory / bundle.ENV_FILE_NAME
    try:
        text = env_path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        indexes = [
            index
            for index, line in enumerate(lines)
            if line.startswith("YOKE_SERVER_IMAGE=")
        ]
        if len(indexes) != 1:
            raise ValueError(
                ".env must contain exactly one active YOKE_SERVER_IMAGE assignment"
            )
        if any(char.isspace() for char in plan.target.image):
            raise ValueError("resolved server image contains whitespace")
        index = indexes[0]
        ending = "\n" if lines[index].endswith("\n") else ""
        lines[index] = f"YOKE_SERVER_IMAGE={plan.target.image}{ending}"
        protection.atomic_replace_bytes(
            env_path,
            "".join(lines).encode("utf-8"),
            mode=stat.S_IMODE(env_path.stat().st_mode),
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        protection.SelfHostProtectionError,
    ) as exc:
        raise SelfHostUpgradeError(
            "bundle-pin",
            f"CLI {plan.target.version} installed, but the bundle pin was not updated.",
            (_diagnostic(str(exc)), _retry_command(plan)),
        ) from exc


def _run_compose_step(plan: UpgradePlan, args: Sequence[str], *, code: str) -> None:
    command = (plan.docker_executable, "compose", *args)
    try:
        completed = _run_capture(
            command, cwd=plan.directory, timeout=COMPOSE_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _compose_error(plan, code, str(exc)) from exc
    if completed.returncode != 0:
        raise _compose_error(plan, code, _completed_diagnostic(completed))


def _compose_error(
    plan: UpgradePlan, code: str, diagnostic: str
) -> SelfHostUpgradeError:
    action = "pull the pinned server image" if code == "compose-pull" else "restart"
    return SelfHostUpgradeError(
        code,
        f"CLI and bundle pin reached {plan.target.version}, but Compose could not {action}.",
        (_diagnostic(diagnostic), *_compose_recovery(plan)),
    )


def _read_server_image(env_path: Path) -> str:
    try:
        matches = [
            line.split("=", 1)[1]
            for line in env_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("YOKE_SERVER_IMAGE=")
        ]
    except (OSError, UnicodeError) as exc:
        raise bundle.SelfHostBundleError(f"could not read {env_path}: {exc}") from exc
    if len(matches) != 1 or not matches[0].strip():
        raise bundle.SelfHostBundleError(
            f"{env_path} must contain exactly one active YOKE_SERVER_IMAGE assignment"
        )
    return matches[0].strip()


def _run_capture(
    command: Sequence[str], *, cwd: Path | None = None, timeout: float
) -> subprocess.CompletedProcess[str]:
    return _RUN(
        tuple(command),
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def _retry_command(plan: UpgradePlan) -> str:
    return (
        "Retry: yoke self-host upgrade --dir "
        f"{shlex.quote(str(plan.directory))} --channel "
        f"{shlex.quote(plan.target.channel)} --yes"
    )


def _compose_recovery(plan: UpgradePlan) -> tuple[str, ...]:
    directory = shlex.quote(str(plan.directory))
    return (
        "Retry the preserved pinned bundle:",
        f"cd {directory} && docker compose pull core",
        f"cd {directory} && docker compose up -d",
    )


def _completed_diagnostic(completed: subprocess.CompletedProcess[str]) -> str:
    return _diagnostic(completed.stderr or completed.stdout or "")


def _diagnostic(value: str) -> str:
    text = redact_api_tokens(str(value or "")).strip()
    printable = "".join(char if char.isprintable() else " " for char in text)
    return printable[-2048:] or "No additional diagnostic was reported."


__all__ = [
    "SelfHostUpgradeError",
    "UpgradePlan",
    "execute_upgrade",
    "plan_upgrade",
]
