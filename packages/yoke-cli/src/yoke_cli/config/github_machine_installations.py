"""Cached GitHub installation validation and permission reporting."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts import github_app_installation_permissions, github_app_snapshot
from yoke_contracts import github_installation_urls, github_origin
from yoke_contracts.machine_config import schema as contract


def permission_report(installations: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for installation in installations:
        raw_permissions = installation.get("permissions")
        evaluation = (
            github_app_installation_permissions
            .evaluate_installation_repository_permissions(
                raw_permissions if isinstance(raw_permissions, Mapping) else {}
            )
        )
        items.append({
            "installation_id": installation.get("installation_id"),
            "account_login": installation.get("account_login"),
            "suspended": bool(installation.get("suspended")),
            "evaluation": evaluation,
            **({"settings_url": installation["html_url"]}
               if installation.get("html_url") else {}),
        })
    return {
        "ok": None if not items else all(
            item["evaluation"]["ok"] for item in items
        ),
        "usable": None if not items else any(
            item["evaluation"]["ok"] and not item["suspended"] for item in items
        ),
        "mode": "github_app_installation",
        "items": items,
    }


def safe_installations(github: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = github.get("installations")
    installations = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, Mapping):
            continue
        try:
            normalized = dict(item)
            normalized["account_login"] = github_app_snapshot.user_login(
                item.get("account_login"), "installation.account_login",
            )
            normalized["account_type"] = github_app_snapshot.account_type(
                item.get("account_type"),
            )
            normalized["app_slug"] = github_app_snapshot.app_slug(
                item.get("app_slug"),
            )
            normalized["repository_selection"] = (
                github_app_snapshot.repository_selection(
                    item.get("repository_selection"),
                )
            )
            normalized["permissions"] = github_app_snapshot.permissions(
                item.get("permissions", {}),
            )
        except github_app_snapshot.GitHubAppSnapshotError:
            continue
        installations.append(normalized)
    web_url = str(github.get("web_url") or contract.DEFAULT_GITHUB_WEB_URL)
    for installation in installations:
        html_url = installation.get("html_url")
        if not html_url:
            continue
        try:
            installation["html_url"] = github_installation_urls.validated_settings_url(
                str(html_url), web_url=web_url,
                installation_id=installation.get("installation_id"),
                account_login=str(installation.get("account_login") or ""),
            )
        except github_origin.GitHubApiOriginError:
            installation.pop("html_url", None)
    return installations


def identity_mismatch(
    github: Mapping[str, Any],
    installations: list[dict[str, Any]],
) -> bool:
    expected_id = github.get("app_id")
    expected_slug = github.get("app_slug")
    return any(
        item.get("app_id") != expected_id
        or item.get("app_slug") != expected_slug
        for item in installations
    )


__all__ = ["identity_mismatch", "permission_report", "safe_installations"]
