"""Setup installs the release its server serves and re-runs itself on it.

The project layer is bound to exactly one CLI release, so setup never applies
a layer built for another release. Setup checks the served release when it
starts (``setup_release_start``); this module owns the install and re-run both
checks share, and the follow when Apply still meets a different release (the
server moved while the wizard was open, or the start could not know the server
yet). Then setup installs exactly that release while it holds the apply lock
(the lock the relay's release follow also takes), records
``cli_followed_release`` in the run report, and the command re-runs itself as
``yoke setup --resume RUN-ID`` on the new CLI once the lock is released. A
resumed run reopens with its saved answers, so the follow costs one Review.

The Apply follow runs at most once per run, from a packaged install, only when
no secret came from stdin and the setup's connection is the machine-active
one; otherwise setup keeps the ``setup_bundle_version_mismatch`` refusal. The
active relay drives the CLI to its server's release in either direction, so an
older served release is followed the same way as a newer one.
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

from yoke_cli.config import install_binding, self_update, setup_release_marker
from yoke_cli.project_install.validate import CliReleaseMismatch

FINAL_STATUS = "release-followed"


class FollowBlocked(RuntimeError):
    """Setup cannot install the served release itself; the text names why."""


class ReleaseFollowed(Exception):
    """Setup installed the served release; the command resumes the run on it."""

    def __init__(
        self, run_id: str, running: str, served: str, yoke_bin: str, *, server: str = ""
    ) -> None:
        self.run_id = run_id
        self.running = running
        self.served = served
        self.yoke_bin = yoke_bin
        # Answers given before the follow that the rerun must not ask again.
        self.carried_args: list[str] = []
        then = (
            f"to match the project layer the server supplied; resuming setup run {run_id}"
            if run_id
            else f"because {server} serves it; restarting setup on it"
        )
        super().__init__(f"installed Yoke {served} in place of {running} {then}")

    def record(self) -> dict[str, str]:
        return {"from": self.running, "to": self.served}


def install_exact(version: str) -> str:
    """Install exactly *version* as this machine's CLI; return its launcher."""
    try:
        install_binding.require_packaged_install("yoke setup")
    except install_binding.SourceCheckoutError as exc:
        raise FollowBlocked(str(exc)) from exc
    yoke_bin = shutil.which("yoke")
    if not yoke_bin:
        raise FollowBlocked("the `yoke` executable is not on PATH")
    try:
        self_update.install_release(self_update.resolve_target(version=version), yoke_bin)
    except self_update.ScheduledInstallRefused:
        raise  # it carries its own recovery
    except self_update.SelfUpdateError as exc:
        raise FollowBlocked(str(exc)) from exc
    return yoke_bin


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
        yoke_bin = install_exact(mismatch.target)
    except self_update.ScheduledInstallRefused as exc:
        raise ProjectInstallError(str(exc)) from exc
    except FollowBlocked as exc:
        raise ProjectInstallError(mismatch.refusal(str(exc))) from exc
    return ReleaseFollowed(run_id, mismatch.running, mismatch.target, yoke_bin)


def _blocking_cause(
    mismatch: CliReleaseMismatch, kwargs: Mapping[str, Any], run_id: str
) -> str:
    marker = setup_release_marker.current()
    if marker and marker["run_id"] == run_id:
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


def resume(followed: ReleaseFollowed, parsed: Any, args: list[str]) -> int:
    """Re-run setup on the newly installed CLI.

    A follow during Apply resumes its run; one before any project question
    reruns the same command (an agent rerun drops the answers it already gave).
    """
    print(f"Setup {followed}.", file=sys.stderr)
    if followed.run_id:
        rerun = ["setup", "--resume", followed.run_id, *mode_flags(parsed)]
    elif getattr(parsed, "agent", False):
        rerun = ["setup", *mode_flags(parsed)]
    else:
        rerun = ["setup", *args]
    if followed.carried_args and followed.carried_args[0] not in rerun:
        rerun += followed.carried_args
    return run_on_release(
        followed.yoke_bin,
        rerun,
        setup_release_marker.encode(followed.running, followed.served, followed.run_id),
    )


def run_on_release(yoke_bin: str, args: list[str], marker: str) -> int:
    """Replace this process with ``yoke ARGS`` on the installed release."""
    argv = [yoke_bin, *args]
    env = {**os.environ, setup_release_marker.FOLLOWED_RELEASE_ENV: marker}
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        # Windows exec starts a new process and the old one exits at once, so
        # the caller would lose the exit status: wait for the new run.
        return subprocess.run(argv, env=env, check=False).returncode
    os.execve(yoke_bin, argv, env)
    return 1  # pragma: no cover - execve does not return


__all__ = [
    "FINAL_STATUS",
    "FollowBlocked",
    "ReleaseFollowed",
    "install_exact",
    "install_served",
    "mode_flags",
    "resume",
    "run_on_release",
]
