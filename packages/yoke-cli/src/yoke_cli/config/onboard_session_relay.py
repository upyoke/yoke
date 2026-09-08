"""Explicit onboard plan and apply bridge for the macOS machine relay.

Every destination that can run a relay gets one, because the relay is what
makes a machine observable and drivable: it registers the harnesses this
machine can actually start, reports session liveness, and executes launch and
resume work. Leaving it out of one destination would make that destination's
install quietly incapable of the operations the product offers everywhere else.

The two destinations differ only in where the relay's build comes from -- an
https plane serves a release the relay pins, while a local universe is served
by the machine the relay runs on, so it runs that machine's installed Yoke.
That difference is owned by the relay installer; onboarding names it in the
plan and the completion summary so the operator sees which one applied.

Setup runs this step every time it applies, including the on-screen retry
after a failure, so the step is convergent rather than unconditional. It first
asks the installer whether this exact relay is already satisfied -- loaded,
running the launchd document this configuration would write now, and pointed at
a present, current build -- and leaves a satisfied relay untouched. Anything
short of satisfied is a real upgrade or repair and installs normally. A retry
therefore cannot unload the working login item it is trying to install, and a
failed attempt reports the installer's own diagnosis instead of replacing it
with a fixed sentence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Mapping

from yoke_cli.config import onboard_apply_progress
from yoke_cli.config.github_response_safety import terminal_safe_text
from yoke_cli.config.onboard_apply_report_metadata import sanitize_text


RELAY_PLIST_TARGET = "~/Library/LaunchAgents/com.upyoke.relay[.<environment-id>].plist"
RELAY_INSTALL_TIMEOUT_SECONDS = 300
#: Reading status only inspects launchd and shakes hands with the plane.
RELAY_STATUS_TIMEOUT_SECONDS = 60
#: How much of the installer's own output the failure carries, from its tail,
#: where the diagnosis lands.
RELAY_DETAIL_MAX_CHARS = 1200
#: Steps every relay install performs, whichever build source it runs.
RELAY_LIFECYCLE_STEPS = (
    ("install-session-relay-plist", RELAY_PLIST_TARGET),
    ("load-session-relay-login-item", "com.upyoke.relay"),
)
#: The build-source step, one per destination.
RELAY_SERVED_RELEASE_STEP = ("reuse-session-relay-token", "existing-api-token")
RELAY_LOCAL_BUILD_STEP = (
    "run-session-relay-on-installed-yoke",
    "this machine's installed Yoke",
)

_SHARED_COMPLETE_LINES = (f"Machine relay plist: {RELAY_PLIST_TARGET}",)
_SERVED_RELEASE_COMPLETE_LINES = (
    "Machine relay runs the release served by its selected environment.",
    "Machine relay uses one stable relay-owned Python with isolated release packages.",
    "Machine relay reuses your existing Yoke API token.",
)
_LOCAL_BUILD_COMPLETE_LINES = (
    "Machine relay runs this machine's installed Yoke, which also serves your "
    "local universe.",
    "Machine relay reaches that universe through your machine config, with no "
    "account or API token.",
)
_REUSED_COMPLETE_LINE = (
    "Machine relay was already installed and current, so setup left it running."
)


class OnboardSessionRelayError(RuntimeError):
    """The explicit relay step could not install its login item."""


@dataclass(frozen=True)
class RelayInstallOutcome:
    """What the relay step did: nothing, because it was already satisfied."""

    installed: bool
    reused: bool


def is_supported(
    *,
    local_destination: bool,
    platform: str | None = None,
) -> bool:
    """Whether this machine can run a relay for the chosen destination."""
    resolved_platform = sys.platform if platform is None else platform
    # launchd is the only supervisor the relay installs into today; the
    # destination no longer decides, because both destinations need a relay.
    del local_destination
    return resolved_platform == "darwin"


def plan_steps(*, local_destination: bool) -> list[dict[str, str]]:
    if not is_supported(local_destination=local_destination):
        return []
    build_step = (
        RELAY_LOCAL_BUILD_STEP if local_destination else RELAY_SERVED_RELEASE_STEP
    )
    return [
        {"action": action, "target": target}
        for action, target in (*RELAY_LIFECYCLE_STEPS, build_step)
    ]


def progress_steps(*, local_destination: bool) -> tuple[tuple[str, str], ...]:
    """The same steps as ``plan_steps``, shaped for the progress emitter."""
    return tuple(
        (step["action"], step["target"])
        for step in plan_steps(local_destination=local_destination)
    )


def setup_complete_lines(
    *, local_destination: bool, reused: bool = False
) -> tuple[str, ...]:
    """What the Setup-complete screen tells the operator about their relay."""
    build_lines = (
        _LOCAL_BUILD_COMPLETE_LINES
        if local_destination
        else _SERVED_RELEASE_COMPLETE_LINES
    )
    reuse_lines = (_REUSED_COMPLETE_LINE,) if reused else ()
    return (*_SHARED_COMPLETE_LINES, *build_lines, *reuse_lines)


def relay_command(
    action: str,
    *,
    config_path: str | Path | None,
    environment: str | None,
) -> list[str]:
    """The packaged installer call for the relay setup is configuring.

    Setup names the environment and config it is writing rather than letting
    the child resolve whatever this machine happens to be pointed at, so the
    relay it converges is always the connection the operator just chose.
    """
    command = [
        sys.executable,
        "-m",
        "yoke_core.tools.install_session_relay",
        action,
    ]
    if environment:
        command += ["--environment", str(environment)]
    if config_path:
        command += ["--config", str(config_path)]
    return command


def _run(
    action: str,
    *,
    config_path: str | Path | None,
    environment: str | None,
    timeout: int,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    return runner(
        relay_command(action, config_path=config_path, environment=environment),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def is_satisfied(
    *,
    config_path: str | Path | None = None,
    environment: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    """Whether this relay already needs no lifecycle write.

    The installer owns that judgement, so setup asks it rather than deciding
    from a subset of the facts. Any refusal to answer -- a crash, a timeout,
    an unreadable config -- is not satisfied, so an unreadable relay is
    repaired rather than skipped.
    """
    try:
        completed = _run(
            "status",
            config_path=config_path,
            environment=environment,
            timeout=RELAY_STATUS_TIMEOUT_SECONDS,
            runner=runner,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def install(
    *,
    local_destination: bool,
    config_path: str | Path | None = None,
    environment: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> RelayInstallOutcome:
    if not is_supported(local_destination=local_destination):
        return RelayInstallOutcome(installed=False, reused=False)
    if is_satisfied(config_path=config_path, environment=environment, runner=runner):
        return RelayInstallOutcome(installed=True, reused=True)
    try:
        completed = _run(
            "install",
            config_path=config_path,
            environment=environment,
            timeout=RELAY_INSTALL_TIMEOUT_SECONDS,
            runner=runner,
        )
    except subprocess.TimeoutExpired as exc:
        raise OnboardSessionRelayError(
            "the machine relay installer did not finish within "
            f"{RELAY_INSTALL_TIMEOUT_SECONDS} seconds; "
            f"{_recovery(environment)}"
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise OnboardSessionRelayError(
            f"the machine relay installer could not start: {exc}; "
            f"{_recovery(environment)}"
        ) from exc
    if completed.returncode != 0:
        raise OnboardSessionRelayError(
            "the machine relay login item could not be installed (installer "
            f"exit {completed.returncode}): "
            f"{installer_detail(completed)}. {_recovery(environment)}"
        )
    return RelayInstallOutcome(installed=True, reused=False)


def installer_detail(completed: subprocess.CompletedProcess[str]) -> str:
    """The installer's own diagnosis, credential-redacted and bounded.

    The installer already names its refusal and recovery; this preserves that
    text instead of replacing it. Redaction runs before the cap so a secret
    can never survive by sitting outside the window.
    """
    raw = str(completed.stderr or "") + str(completed.stdout or "")
    redacted = sanitize_text(raw)
    if not redacted.strip():
        return "the installer reported no diagnostic output"
    return terminal_safe_text(
        redacted[-(RELAY_DETAIL_MAX_CHARS * 2) :],
        maximum_chars=RELAY_DETAIL_MAX_CHARS,
    )


def _recovery(environment: str | None) -> str:
    scope = f" --env {environment}" if environment else ""
    return (
        f"run `yoke{scope} relay status` for the recorded reason, then "
        f"`yoke{scope} relay install` to retry it"
    )


def apply(
    progress: onboard_apply_progress.ProgressCallback | None,
    report: dict[str, Any],
    *,
    local_destination: bool,
    config_path: str | Path | None,
    environment: str | None,
) -> None:
    """Run the relay step and record what it did in the apply report."""
    if not is_supported(local_destination=local_destination):
        return
    steps = progress_steps(local_destination=local_destination)
    onboard_apply_progress.emit_many(progress, steps, "running")
    outcome = install(
        local_destination=local_destination,
        config_path=config_path,
        environment=environment,
    )
    onboard_apply_progress.emit_many(progress, steps, "done")
    report["session_relay"] = report_fragment(
        planned=True,
        installed=outcome.installed,
        local_destination=local_destination,
        reused=outcome.reused,
    )


def report_fragment(
    *,
    planned: bool,
    installed: bool,
    local_destination: bool = False,
    reused: bool = False,
) -> dict[str, Any]:
    return {
        "planned": planned,
        "installed": installed,
        "plist": RELAY_PLIST_TARGET if planned else None,
        "local_build": local_destination,
        "reused": reused,
    }


def report_complete_lines(fragment: Any) -> tuple[str, ...]:
    """Completion lines for an applied report, or none when nothing installed."""
    if not isinstance(fragment, Mapping) or not fragment.get("installed"):
        return ()
    return setup_complete_lines(
        local_destination=bool(fragment.get("local_build")),
        reused=bool(fragment.get("reused")),
    )


__all__ = [
    "OnboardSessionRelayError",
    "RELAY_DETAIL_MAX_CHARS",
    "RELAY_INSTALL_TIMEOUT_SECONDS",
    "RELAY_LIFECYCLE_STEPS",
    "RELAY_LOCAL_BUILD_STEP",
    "RELAY_PLIST_TARGET",
    "RELAY_SERVED_RELEASE_STEP",
    "RELAY_STATUS_TIMEOUT_SECONDS",
    "RelayInstallOutcome",
    "apply",
    "install",
    "installer_detail",
    "is_satisfied",
    "is_supported",
    "plan_steps",
    "progress_steps",
    "relay_command",
    "report_complete_lines",
    "report_fragment",
    "setup_complete_lines",
]
