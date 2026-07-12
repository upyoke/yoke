"""GitHub App access discovery and installation-browser helpers."""

from __future__ import annotations

from http import HTTPStatus
import time
from typing import Any, Callable, Mapping

from yoke_cli.config import github_app_user_api


ACCESS_DISCOVERY_RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0)
ACCESS_DISCOVERY_DEADLINE_SECONDS = 60.0
_TRANSIENT_PROGRESS_FIELDS = frozenset({"user_code", "device_code"})


def report_safe_progress_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Remove one-time authorization material from durable report progress."""
    return {
        key: value
        for key, value in event.items()
        if key not in _TRANSIENT_PROGRESS_FIELDS
    }


def discover_access_with_unauthorized_retry(
    *,
    api_url: str,
    access_token: str,
    opener: Callable[..., Any] | None,
    sleep: Callable[[float], None],
    notify: Callable[[Mapping[str, Any]], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    deadline_seconds: float = ACCESS_DISCOVERY_DEADLINE_SECONDS,
    web_url: str | None = None,
    expected_app_id: int | None = None,
    expected_app_slug: str | None = None,
) -> dict[str, Any]:
    """Retry transient unauthorized responses before classifying access."""
    attempts = 1
    deadline = monotonic() + deadline_seconds
    for delay_seconds in (*ACCESS_DISCOVERY_RETRY_DELAYS_SECONDS, None):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise github_app_user_api.GitHubAppUserApiError(
                "GitHub access discovery exceeded its operation deadline"
            )
        try:
            snapshot = github_app_user_api.discover_access(
                api_url=api_url,
                access_token=access_token,
                opener=opener,
                total_deadline_seconds=remaining,
                monotonic=monotonic,
                web_url=web_url,
            )
            _verify_installation_identity(
                snapshot,
                expected_app_id=expected_app_id,
                expected_app_slug=expected_app_slug,
            )
            return snapshot
        except github_app_user_api.GitHubAppUserApiError as exc:
            if exc.status != HTTPStatus.UNAUTHORIZED or delay_seconds is None:
                raise
            if delay_seconds >= deadline - monotonic():
                raise
            attempts += 1
            if notify is not None:
                notify({
                    "phase": "github_access_propagation_retry",
                    "attempt": attempts,
                    "retry_in_seconds": delay_seconds,
                })
            sleep(delay_seconds)
    raise AssertionError("GitHub access retry loop ended unexpectedly")


def _verify_installation_identity(
    snapshot: Mapping[str, Any],
    *,
    expected_app_id: int | None,
    expected_app_slug: str | None,
) -> None:
    if expected_app_id is None and expected_app_slug is None:
        return
    for item in snapshot.get("installations") or []:
        if not isinstance(item, Mapping):
            continue
        if (
            item.get("app_id") != expected_app_id
            or item.get("app_slug") != expected_app_slug
        ):
            raise github_app_user_api.GitHubAppUserApiError(
                "GitHub returned an installation for a different App profile"
            )


def open_install_page(
    report: dict[str, Any],
    *,
    browser_open: Callable[[str], Any] | None,
    notify: Callable[[Mapping[str, Any]], None] | None,
    pending: bool,
    error_type: type[Exception] = RuntimeError,
) -> None:
    """Open the profile-derived App installation page, if available."""
    import webbrowser

    install_url = str(report.get("install_url") or "").strip()
    if not install_url:
        raise error_type(
            "GitHub App installation URL is unavailable because the configured "
            "GitHub endpoints are invalid"
        )
    opened = False
    try:
        opened = bool((browser_open or webbrowser.open)(install_url))
    except Exception:
        pass
    report.update({"install_url": install_url, "install_browser_opened": opened})
    if pending:
        report["state"] = "pending_installation"
    if notify is not None:
        notify({
            "phase": "app_installation",
            "install_url": install_url,
            "browser_opened": opened,
        })


__all__ = [
    "ACCESS_DISCOVERY_RETRY_DELAYS_SECONDS",
    "ACCESS_DISCOVERY_DEADLINE_SECONDS",
    "discover_access_with_unauthorized_retry",
    "open_install_page",
    "report_safe_progress_event",
]
