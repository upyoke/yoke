"""Non-secret GitHub App metadata for onboarding apply snapshots."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_cli.config.project_github_adoption import GITHUB_ADOPTION_BACKLOG_ONLY


def authorization_source(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    if str(kwargs.get("machine_github_choice") or "") == "connect":
        from yoke_contracts import github_app_tokens

        return {"kind": github_app_tokens.GITHUB_AUTH_KIND_USER_AUTHORIZATION}
    return {"kind": ""}


def binding(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    adoption = str(kwargs.get("project_github_adoption") or "")
    repo = str(kwargs.get("project_github_repo") or "")
    status = str(kwargs.get("project_github_binding_status") or "")
    if not status:
        status = (
            "backlog_only"
            if adoption == GITHUB_ADOPTION_BACKLOG_ONLY or not repo
            else "pending_app_connection"
        )
    return {
        "adoption": adoption,
        "repo": repo,
        "installation_id": str(kwargs.get("project_github_installation_id") or ""),
        "repository_id": str(kwargs.get("project_github_repository_id") or ""),
        "status": status,
        "permission_status": _mapping(kwargs.get("project_github_permission_status")),
        "automation": _mapping(kwargs.get("project_github_automation")),
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


__all__ = ["authorization_source", "binding"]
