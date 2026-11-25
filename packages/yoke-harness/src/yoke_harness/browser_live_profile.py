"""Resolve the loopback DevTools endpoint of one managed Chromium profile."""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from yoke_contracts.process_ancestry import process_start_time
from yoke_contracts.refusal_recovery import compose_refusal

_LOOPBACK = "127.0.0.1"


class LiveProfileError(RuntimeError):
    """The profile must be left alone until its owner or endpoint is available."""


def _profile_in_use(profile: Path) -> bool:
    if sys.platform == "win32":
        # Chromium holds this singleton file for writing and deletes it on
        # close. Probe sharing without changing or creating the file.
        try:
            fd = os.open(profile / "lockfile", os.O_WRONLY | os.O_BINARY)
        except FileNotFoundError:
            return False
        except PermissionError:
            return True
        os.close(fd)
        return False

    try:
        owner = (profile / "SingletonLock").readlink().name
    except FileNotFoundError:
        return False
    host, _, pid = owner.rpartition("-")
    return bool(host and pid.isascii() and pid.isdecimal()) and (
        host != os.uname().nodename or process_start_time(int(pid)) is not None
    )


def _endpoint(profile: Path) -> str:
    port_text, marker_path = (profile / "DevToolsActivePort").read_text(
        encoding="utf-8"
    ).splitlines()
    port = int(port_text)
    if not 0 < port <= 65535 or not re.fullmatch(
        r"/devtools/browser/[0-9a-fA-F-]{36}", marker_path
    ):
        raise ValueError("invalid DevToolsActivePort marker")

    connection = http.client.HTTPConnection(_LOOPBACK, port, timeout=2)
    try:
        connection.request("GET", "/json/version")
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("DevTools did not answer with browser metadata")
        url = urlsplit(json.loads(response.read(16384))["webSocketDebuggerUrl"])
    finally:
        connection.close()
    if url.geturl() != f"ws://{_LOOPBACK}:{port}{marker_path}":
        raise ValueError("DevTools endpoint does not match this profile's marker")
    return url.geturl()


def _close_profile(profile: Path) -> str:
    return f"Finish any open approvals, close the browser using {profile}, then retry"


def live_profile_endpoint(profile: Path) -> str | None:
    """Return the verified endpoint, or None when the profile is free."""
    try:
        return _endpoint(profile)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, http.client.HTTPException):
        try:
            if not _profile_in_use(profile):
                return None
        except OSError as error:
            raise LiveProfileError(
                compose_refusal(
                    f"browser_sign_in_profile_unavailable: could not inspect {profile}",
                    recovery=f"Restore access to the browser profile and retry ({error.strerror})",
                )
            ) from None
    raise LiveProfileError(
        compose_refusal(
            "browser_sign_in_profile_unavailable: sign-in could not be verified "
            f"through the managed endpoint for the open profile {profile}",
            recovery=_close_profile(profile),
        )
    )


def require_closed_profile(profile: Path) -> None:
    """Protect the open browser before authorization changes its profile."""
    if live_profile_endpoint(profile) is not None:
        raise LiveProfileError(
            compose_refusal(
                f"browser_sign_in_profile_in_use: authorization needs exclusive access "
                f"to {profile}",
                recovery=_close_profile(profile),
            )
        )
