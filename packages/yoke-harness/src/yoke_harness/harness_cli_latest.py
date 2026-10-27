"""Compare recorded harness CLI versions with each vendor's latest release.

A QA plan's golden refresh and an operator's hand golden capture both ask the
same question of the release channels, so both read them here. A hand capture
that records CLIs behind latest warns, because the next QA plan on the host
refreshes that golden and replaces it.
"""

from __future__ import annotations

import sys
import urllib.request
from typing import Any, Callable, Mapping

from yoke_contracts.harness_cli_releases import (
    HARNESS_CLI_RELEASES,
    outdated_harness_clis,
)
from yoke_harness.golden_harness_clis import PROVISIONING_DOC

LATEST_FETCH_TIMEOUT_SECONDS = 30


class LatestReleaseUnavailable(RuntimeError):
    """A release channel did not answer with a version."""


def fetch_release_channel(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "yoke-golden-refresh"})
    with urllib.request.urlopen(request, timeout=LATEST_FETCH_TIMEOUT_SECONDS) as reply:
        return reply.read().decode("utf-8")


def latest_harness_cli_versions(fetch: Callable[[str], str]) -> dict[str, str]:
    """Return each harness id's latest published CLI version, or raise."""
    latest = {}
    for release in HARNESS_CLI_RELEASES:
        try:
            latest[release.harness_id] = release.latest_version(
                fetch(release.latest_url)
            )
        except Exception as error:
            raise LatestReleaseUnavailable(
                f"{release.latest_url} did not answer with a {release.harness_id} "
                f"release ({type(error).__name__}: {error})"
            ) from error
    return latest


def warn_capture_behind_latest(
    operation: str,
    result: Mapping[str, Any] | None,
    payload: Mapping[str, Any],
    *,
    fetch: Callable[[str], str] = fetch_release_channel,
) -> str | None:
    """Warn when a verified hand capture records harness CLIs behind latest."""
    if operation != "golden_capture" or (result or {}).get("status") != "verified":
        return None
    recorded = next(
        (
            row["harness_cli_versions"]
            for row in payload.get("checks") or []
            if row.get("harness_cli_versions")
        ),
        None,
    )
    if recorded is None:
        return None
    try:
        latest = latest_harness_cli_versions(fetch)
    except LatestReleaseUnavailable as error:
        warning = (
            "warning golden_harness_latest_unavailable: could not compare the "
            f"captured harness CLIs with their latest releases ({error}); the "
            "next QA plan on this host compares them and refreshes this golden "
            "if one is behind."
        )
    else:
        outdated = outdated_harness_clis(recorded, latest)
        if not outdated:
            return None
        behind = ", ".join(
            f"{harness} {recorded.get(harness) or 'absent'} < {latest[harness]}"
            for harness in outdated
        )
        warning = (
            f"warning golden_harness_clis_behind_latest: {behind}. The next QA "
            "plan on this host installs the newer CLIs and captures a "
            "replacement golden. To control that golden yourself, install "
            f"{', '.join(outdated)} as the test user following "
            f"{PROVISIONING_DOC}, then capture again."
        )
    print(f"# test-machine golden-capture: {warning}", file=sys.stderr, flush=True)
    return warning


__all__ = [
    "LatestReleaseUnavailable",
    "fetch_release_channel",
    "latest_harness_cli_versions",
    "warn_capture_behind_latest",
]
