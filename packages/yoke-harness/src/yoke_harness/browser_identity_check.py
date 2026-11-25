"""Check, site by site, whether one browser identity is still signed in.

Use a managed profile's live endpoint when supplied and the headless verifier
when the profile is free. Report each declared site separately without typing
or signing in.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from yoke_contracts.browser_identity import BrowserIdentity
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_cli.config.browser_profile_cookies import (
    SignInCookieError,
    keep_sign_in_cookies,
)

SIGNED_IN = "signed_in"
EXPIRED = "expired"
UNREACHABLE = "unreachable"
_SUMMARY_WORD = {SIGNED_IN: "ok", EXPIRED: "expired", UNREACHABLE: "unreachable"}
CHECK_TIMEOUT_SECONDS = 300


class SignInCheckError(RuntimeError):
    """The check itself could not run; no site state was learned."""


def stop_profile_daemon(client, profile: Path) -> None:
    """Release the profile lock a running daemon on this profile holds."""
    state = client.DaemonState.load(client._state_file_path(str(profile)))
    if state is None or not client.daemon_running(state):
        return
    try:
        client.daemon_stop(profile_dir=str(profile))
    except RuntimeError:
        pass  # Already gone between the check and the stop.


def check_identity(
    identity: BrowserIdentity,
    profile: Path | None,
    *,
    node: Path,
    runtime_dir: Path,
    env: dict[str, str],
    live_endpoint: str | None = None,
) -> list[dict[str, Any]]:
    """Return one ``{site, state, detail, origin, account}`` per declared site."""
    if not identity.sites:
        return []
    if profile is None:
        outcomes = [
            {"site": check.site, "state": EXPIRED, "detail": "no profile signed in yet"}
            for check in identity.sites
        ]
    else:
        outcomes = _probe_sites(identity, profile, node, runtime_dir, env, live_endpoint)
    by_site = {check.site: check for check in identity.sites}
    return [
        {
            **outcome,
            "origin": by_site[outcome["site"]].origin,
            "account": by_site[outcome["site"]].account,
        }
        for outcome in outcomes
    ]


def _probe_sites(identity, profile, node, runtime_dir, env, live_endpoint):
    if live_endpoint is None:
        try:
            keep_sign_in_cookies(profile)
        except SignInCookieError as exc:
            raise SignInCheckError(f"browser_sign_in_check_failed: {exc}") from None
    target = (
        ["--live-endpoint", live_endpoint]
        if live_endpoint
        else ["--profile-dir", str(profile)]
    )
    try:
        result = subprocess.run(
            [
                str(node),
                str(runtime_dir / "src" / "verify-sign-in.js"),
                *target,
                "--checks",
                json.dumps([check.as_probe() for check in identity.sites]),
            ],
            cwd=str(runtime_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _probe_failed(
            profile, identity.name, live_endpoint, type(exc).__name__
        ) from None
    if result.returncode == 0:
        try:
            return json.loads(result.stdout)["sites"]
        except (ValueError, KeyError, TypeError):
            pass
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    raise _probe_failed(
        profile,
        identity.name,
        live_endpoint,
        detail[-1] if detail and not live_endpoint else f"exit {result.returncode}",
    ) from None


def _probe_failed(profile, identity, live_endpoint, detail):
    if live_endpoint:
        return SignInCheckError(
            compose_refusal(
                "browser_sign_in_profile_unavailable: sign-in could not be verified "
                f"through the managed endpoint for the open profile {profile} ({detail})",
                recovery="Finish any open approvals, close that browser, then retry",
            )
        )
    return SignInCheckError(
        "browser_sign_in_check_failed: the headless sign-in check for "
        f"identity {identity!r} failed ({detail}). Run `yoke qa browser status` "
        "to check the browser runtime, then retry."
    )


def sites_in(sites: list[dict[str, Any]], state: str) -> list[dict[str, Any]]:
    return [site for site in sites if site["state"] == state]


def summarize(identity: str, sites: list[dict[str, Any]]) -> str:
    """One line per identity, for example ``buyer: google ok, paypal expired``."""
    if not sites:
        return f"{identity}: declares no sites to check"
    return f"{identity}: " + ", ".join(
        f"{site['site']} {_SUMMARY_WORD[site['state']]}" for site in sites
    )


def sign_in_request(identity: str, sites: list[dict[str, Any]]) -> list[str]:
    """Name, for the human, each site to sign into and the account to use."""
    return [
        f"Sign in to {site['site']} ({site['origin']}) for identity {identity}"
        + (f" as {site['account']}" if site["account"] else "")
        + "."
        for site in sites
    ]


__all__ = [
    "EXPIRED",
    "SIGNED_IN",
    "UNREACHABLE",
    "SignInCheckError",
    "check_identity",
    "sign_in_request",
    "sites_in",
    "stop_profile_daemon",
    "summarize",
]
