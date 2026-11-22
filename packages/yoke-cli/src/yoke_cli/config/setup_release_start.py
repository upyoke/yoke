"""Setup moves onto the served release before it asks any project question.

Setup reads its server's public ``GET {api_url}/v1/health`` ``engine_version``
twice: when it starts, if the server is already known (``--connect``,
``--api-url``, a saved connection or a resumed run), and right after sign-in
saves the connection, which is the first moment a fresh hosted setup knows its
org's server. When the served release is a different downloadable release,
setup installs exactly that release under the apply lock and reruns the same
command on it, so no answer is lost: the rerun reuses the saved connection.
A release that moves later is followed during Apply (``setup_release_follow``).

A source checkout never follows (git updates it), an unreadable health reply
leaves the decision to Apply's bundle check, and a process already started by
a follow does not follow again.
"""

from __future__ import annotations

import sys
from typing import Any

from yoke_contracts.engine_version import local_handshake_version
from yoke_contracts.onboard_destinations import DESTINATION_LOCAL
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.release_version import release_version

from yoke_cli.config import install_binding, onboard_apply_lock, server_connect
from yoke_cli.config import setup_release_follow as follow
from yoke_cli.config import setup_release_marker
from yoke_cli.transport.installed_cli_staleness import update_recovery

HEALTH_TIMEOUT_SECONDS = 10.0


class StartFollowRefused(RuntimeError):
    """Setup could not install the release its server serves."""


def check_at_start(parsed: Any, destination: str | None) -> None:
    """Install the served release before any question; raises ReleaseFollowed."""
    if destination == DESTINATION_LOCAL:
        return
    followed = _follow(str(getattr(parsed, "api_url", None) or ""))
    if followed is not None:
        raise followed


def follow_after_sign_in(api_url: str) -> follow.ReleaseFollowed | None:
    """The same check, once sign-in has saved this machine's connection."""
    return _follow(api_url)


def refuse(exc: StartFollowRefused) -> int:
    print(f"error: {exc}", file=sys.stderr)
    return 1


def _follow(api_url: str) -> follow.ReleaseFollowed | None:
    if not api_url or setup_release_marker.current() is not None:
        return None
    running = local_handshake_version()
    served = _served_release(api_url)
    if not running or not served or served == running:
        return None
    try:
        target = release_version(served)
        install_binding.require_packaged_install("yoke setup")
    except (ValueError, install_binding.SourceCheckoutError):
        return None
    try:
        with onboard_apply_lock.acquire():
            yoke_bin = follow.install_exact(target)
    except (follow.FollowBlocked, onboard_apply_lock.OnboardApplyBusy) as exc:
        raise StartFollowRefused(
            compose_refusal(
                f"setup_release_install_failed: this CLI is {running}, but "
                f"{api_url} serves {target}, and setup could not install it: {exc}",
                recovery=f"{update_recovery(target)}, then run this setup command again.",
            )
        ) from exc
    return follow.ReleaseFollowed("", running, target, yoke_bin, server=api_url)


def _served_release(api_url: str) -> str:
    try:
        health = server_connect.verify_server_health(
            api_url, timeout_s=HEALTH_TIMEOUT_SECONDS
        )
    except server_connect.ServerConnectError:
        return ""
    return str(health.get("engine_version") or "").strip()


__all__ = [
    "StartFollowRefused",
    "check_at_start",
    "follow_after_sign_in",
    "refuse",
]
