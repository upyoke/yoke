"""Non-mutating verification for repository-scoped GitHub user tokens."""

from __future__ import annotations

import urllib.parse
from typing import Any, Mapping, Protocol

from yoke_contracts import github_user_token_permissions as user_token_contract


class RepositoryTokenVerificationError(RuntimeError):
    """Repository-scoped token probes did not satisfy Yoke's contract."""


class RequestJson(Protocol):
    def __call__(
        self,
        api_url: str,
        path: str,
        token: str,
        *,
        query: Mapping[str, str] | None = None,
    ) -> tuple[Any, list[str]]: ...


def verify_read_access(
    api_url: str,
    token: str,
    identity: Mapping[str, Any],
    repo_full_name: str,
    *,
    request_json: RequestJson,
) -> dict[str, Any]:
    """Run GET-only repository-permission probes against one accessible repo."""
    owner, repo = _repo_parts(repo_full_name)
    checked: list[dict[str, Any]] = []
    environment_name = _first_environment_name(
        api_url,
        token,
        owner,
        repo,
        request_json=request_json,
    )
    for permission in user_token_contract.REQUIRED_REPOSITORY_USER_TOKEN_PERMISSIONS:
        probe = user_token_contract.repository_read_probe(permission.key)
        if not probe.path_template:
            checked.append(_probe_skipped(permission, probe.unavailable_reason))
            continue
        if probe.needs_existing_environment and not environment_name:
            checked.append(_probe_skipped(permission, probe.unavailable_reason))
            continue
        path = _probe_path(
            probe.path_template,
            owner=owner,
            repo=repo,
            environment_name=environment_name,
        )
        try:
            request_json(api_url, path, token, query=probe.query)
        except RuntimeError as exc:
            checked.append({
                "key": permission.key,
                "label": permission.label,
                "required": permission.access,
                "ok": False,
                "status": "failed",
                "probe": path,
                "error": str(exc),
            })
            continue
        checked.append({
            "key": permission.key,
            "label": permission.label,
            "required": permission.access,
            "ok": True,
            "status": "read_verified",
            "probe": path,
        })
    failures = [check for check in checked if check["status"] == "failed"]
    if failures:
        missing = ", ".join(str(check["label"]) for check in failures)
        raise RepositoryTokenVerificationError(
            "GitHub credential is valid"
            f" for {identity.get('login')}, but non-mutating repository"
            f" read checks failed for {missing} against {repo_full_name}."
            " Enable those permissions through the Yoke GitHub App, then retry."
        )
    verified = [str(check["label"]) for check in checked if check["ok"]]
    skipped = [str(check["label"]) for check in checked if not check["ok"]]
    summary = "non-mutating read checks passed"
    if verified:
        summary += " for " + ", ".join(verified)
    if skipped:
        summary += "; not checked without writing or an existing resource: "
        summary += ", ".join(skipped)
    summary += ". Repository write grants were not mutated during onboarding."
    return {
        "ok": True,
        "mode": "repository_token_non_mutating",
        "required": [
            {
                "key": permission.key,
                "label": permission.label,
                "access": permission.access,
            }
            for permission in user_token_contract.REQUIRED_REPOSITORY_USER_TOKEN_PERMISSIONS
        ],
        "repo": repo_full_name,
        "write_verified": False,
        "checks": checked,
        "summary": summary,
    }


def _probe_skipped(
    permission: user_token_contract.GitHubUserTokenPermission,
    reason: str,
) -> dict[str, Any]:
    return {
        "key": permission.key,
        "label": permission.label,
        "required": permission.access,
        "ok": False,
        "status": "not_checked",
        "reason": reason,
    }


def _first_environment_name(
    api_url: str,
    token: str,
    owner: str,
    repo: str,
    *,
    request_json: RequestJson,
) -> str | None:
    path = _probe_path(
        "/repos/{owner}/{repo}/environments",
        owner=owner,
        repo=repo,
    )
    try:
        payload, _scopes = request_json(
            api_url,
            path,
            token,
            query={"per_page": "1"},
        )
    except RuntimeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    environments = payload.get("environments")
    if not isinstance(environments, list):
        return None
    for environment in environments:
        if isinstance(environment, Mapping) and environment.get("name"):
            return str(environment["name"])
    return None


def _repo_parts(github_repo: str) -> tuple[str, str]:
    parts = github_repo.strip().split("/")
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise RepositoryTokenVerificationError("GitHub repo must be OWNER/REPO")
    return parts[0].strip(), parts[1].strip()


def _probe_path(
    template: str,
    *,
    owner: str,
    repo: str,
    environment_name: str | None = None,
) -> str:
    replacements = {
        "owner": urllib.parse.quote(owner, safe=""),
        "repo": urllib.parse.quote(repo, safe=""),
        "environment_name": urllib.parse.quote(environment_name or "", safe=""),
    }
    return template.format(**replacements)


__all__ = [
    "RepositoryTokenVerificationError",
    "RequestJson",
    "verify_read_access",
]
