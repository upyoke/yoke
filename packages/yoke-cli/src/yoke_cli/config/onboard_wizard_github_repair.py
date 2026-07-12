"""Bounded repair-link copy for GitHub installation screens."""

from __future__ import annotations

from typing import Any


REPAIR_URL_LIMIT = 20
_INSTALLATION_REPAIR_CODES = frozenset({
    "github_app_installation_suspended",
    "github_app_installation_permissions_incomplete",
    "github_app_no_usable_installation",
})
_AUTHORIZATION_REPAIR_CODES = frozenset({
    "github_authorization_kind_unknown",
    "github_authorization_invalid",
    "github_refresh_credential_invalid",
    "github_refresh_credential_ref_missing",
    "github_authorization_revoked",
    "github_user_token_unavailable",
    "github_live_check_failed",
})


def url_lines(report: dict[str, Any]) -> list[str]:
    permissions = report.get("permissions")
    items = permissions.get("items") if isinstance(permissions, dict) else []
    values: list[tuple[str, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("settings_url") or "").strip()
        if url:
            values.append((str(item.get("account_login") or "GitHub account"), url))
    lines = [
        f"Repair {account}: {url}"
        for account, url in values[:REPAIR_URL_LIMIT]
    ]
    if len(values) > REPAIR_URL_LIMIT:
        lines.append(
            f"{len(values) - REPAIR_URL_LIMIT} more installation repair links "
            "are available from `yoke github status`."
        )
    return lines


def issue_codes(report: dict[str, Any]) -> set[str]:
    return {
        str(item.get("code") or "")
        for item in report.get("issues") or []
        if isinstance(item, dict)
    }


def needs_installation_repair(report: dict[str, Any]) -> bool:
    codes = issue_codes(report)
    authorization = report.get("authorization")
    return bool(
        codes & _INSTALLATION_REPAIR_CODES
        and not codes & _AUTHORIZATION_REPAIR_CODES
        and isinstance(authorization, dict)
        and authorization.get("present") is True
    )


def retryable_live_check(report: dict[str, Any]) -> bool:
    authorization = report.get("authorization")
    return bool(
        "github_live_check_failed" in issue_codes(report)
        and isinstance(authorization, dict)
        and authorization.get("present") is True
        and authorization.get("status") == "authorized"
    )


__all__ = [
    "REPAIR_URL_LIMIT",
    "issue_codes",
    "needs_installation_repair",
    "retryable_live_check",
    "url_lines",
]
