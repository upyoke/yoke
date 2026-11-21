"""Setup installs the release its connection serves, then resumes the same run.

The project layer is bound to exactly one CLI release, so setup never applies
a layer built for another release. When the server serves a different
downloadable release, setup installs exactly that release while it still
holds the apply lock (the lock the relay's release follow also takes), records
``cli_followed_release`` in the run report, and the command re-runs itself as
``yoke setup --resume RUN-ID`` on the new CLI once the lock is released.

Setup follows only when the active connection's relay would keep the CLI on
that release (the setup's connection is the machine-active one), at most once
per run, from a packaged install, and only when no secret came from stdin. In
every other case it keeps the ``setup_bundle_version_mismatch`` refusal.
Because the active relay drives the CLI to its server's release in either
direction, an older served release is followed the same way as a newer one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any, Mapping

from yoke_contracts.machine_config import reader as machine_config
from yoke_contracts.machine_config.schema_connections import configured_active_env
from yoke_contracts.project_contract.install_error import ProjectInstallError

from yoke_cli.config import install_binding, self_update
from yoke_cli.project_install.validate import CliReleaseMismatch

# Set on the resumed process to the run id that already followed once.
FOLLOWED_RUN_ENV = "YOKE_SETUP_FOLLOWED_RELEASE_RUN"
FINAL_STATUS = "release-followed"


class ReleaseFollowed(Exception):
    """Setup installed the served release; the command resumes the run on it."""

    def __init__(self, run_id: str, running: str, served: str, yoke_bin: str) -> None:
        self.run_id = run_id
        self.running = running
        self.served = served
        self.yoke_bin = yoke_bin
        super().__init__(
            f"installed Yoke {served} in place of {running} to match the "
            f"project layer the server supplied; resuming setup run {run_id}"
        )

    def record(self) -> dict[str, str]:
        return {"from": self.running, "to": self.served}


def install_served(
    mismatch: CliReleaseMismatch, kwargs: Mapping[str, Any], run_id: str
) -> ReleaseFollowed:
    """Install the served release under the held apply lock, or refuse."""
    if mismatch.target is None:
        raise mismatch
    cause = _blocking_cause(mismatch, kwargs, run_id)
    if cause:
        raise ProjectInstallError(mismatch.refusal(cause)) from mismatch
    try:
        install_binding.require_packaged_install("yoke setup")
    except install_binding.SourceCheckoutError as exc:
        raise ProjectInstallError(mismatch.refusal(str(exc))) from exc
    yoke_bin = shutil.which("yoke")
    if not yoke_bin:
        raise ProjectInstallError(
            mismatch.refusal("the `yoke` executable is not on PATH")
        ) from mismatch
    try:
        self_update.install_release(
            self_update.resolve_target(version=mismatch.target), yoke_bin
        )
    except self_update.SelfUpdateError as exc:
        raise ProjectInstallError(mismatch.refusal(str(exc))) from exc
    return ReleaseFollowed(run_id, mismatch.running, mismatch.target, yoke_bin)


def _blocking_cause(
    mismatch: CliReleaseMismatch, kwargs: Mapping[str, Any], run_id: str
) -> str:
    if os.environ.get(FOLLOWED_RUN_ENV) == run_id:
        return (
            f"this run already installed a release once and its CLI is still "
            f"{mismatch.running}"
        )
    if kwargs.get("token_source_kind") == "stdin":
        return "the token came from stdin, which a resumed run cannot read again"
    config_path = kwargs.get("config_path")
    env_name = str(kwargs.get("env_name") or "") or machine_config.active_env(
        config_path
    )
    active = configured_active_env(machine_config.load_config(config_path))
    if env_name != active:
        return (
            f"connection {env_name!r} is not this machine's active connection "
            f"({active or 'none'}), so no relay keeps the CLI on its release"
        )
    return ""


def mode_flags(parsed: Any) -> list[str]:
    """The shell and mode flags the resumed run needs to behave the same way."""
    flags = [
        flag
        for flag, given in (
            ("--json", getattr(parsed, "json_mode", False)),
            ("--agent", getattr(parsed, "agent", False)),
            ("--tui", getattr(parsed, "tui", False)),
            ("--non-interactive", getattr(parsed, "non_interactive", False)),
            ("--yes", getattr(parsed, "apply", False)),
            ("--skip-identity-check", getattr(parsed, "skip_identity_check", False)),
        )
        if given
    ]
    config_path = getattr(parsed, "config_path", None)
    return [*flags, "--config", str(config_path)] if config_path else flags


def resume(followed: ReleaseFollowed, parsed: Any) -> int:
    """Re-run ``yoke setup --resume`` on the newly installed CLI."""
    argv = [
        followed.yoke_bin,
        "setup",
        "--resume",
        followed.run_id,
        *mode_flags(parsed),
    ]
    env = {**os.environ, FOLLOWED_RUN_ENV: followed.run_id}
    print(f"Setup {followed}.", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        # Windows exec starts a new process and the old one exits at once, so
        # the caller would lose the exit status: wait for the resumed run.
        return subprocess.run(argv, env=env, check=False).returncode
    os.execve(followed.yoke_bin, argv, env)
    return 1  # pragma: no cover - execve does not return


__all__ = [
    "FINAL_STATUS",
    "FOLLOWED_RUN_ENV",
    "ReleaseFollowed",
    "install_served",
    "mode_flags",
    "resume",
]
