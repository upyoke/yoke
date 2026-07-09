"""GitHub API verification helpers for machine credentials."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from yoke_contracts import github_user_token_permissions as user_token_contract
from yoke_cli.config import github_machine_repository_token
from yoke_cli.config import github_token_capability

_TIMEOUT_S = 20.0
_USER_PATH = "/user"
_REPOS_PATH = "/user/repos"
_ORGS_PATH = "/user/orgs"


class GitHubMachineVerificationError(RuntimeError):
    """A machine GitHub credential check failed."""


def verify(
    api_url: str,
    token: str,
    *,
    github_repo: str | None = None,
) -> dict[str, Any]:
    user, scopes = _request_json(api_url, _USER_PATH, token)
    repos, repo_scopes = _request_json(
        api_url,
        _REPOS_PATH,
        token,
        query={
            "per_page": "100",
            "affiliation": "owner,collaborator,organization_member",
        },
    )
    orgs, org_scopes = _request_json(
        api_url, _ORGS_PATH, token, query={"per_page": "100"}
    )
    repo_detail = None
    direct_repo_scopes: list[str] = []
    if github_repo:
        repo_detail, direct_repo_scopes = _request_json(
            api_url, _repo_path(github_repo), token,
        )
    merged_scopes = sorted(
        set(scopes) | set(repo_scopes) | set(org_scopes) | set(direct_repo_scopes)
    )
    identity = _identity(user)
    access = _access(identity, repos, orgs, requested_repo=repo_detail)
    permissions = _verify_permission_contract(
        api_url,
        token,
        identity,
        access,
        merged_scopes,
    )
    result = {
        "identity": identity,
        "access": access,
        "scopes": merged_scopes,
        "permissions": permissions,
    }
    result["capability"] = _detect_capability(api_url, token, result)
    return result


def _detect_capability(
    api_url: str,
    token: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Best-effort capability detection; a probe failure never breaks verify."""
    try:
        return github_token_capability.detect_capability(api_url, token, result)
    except Exception:  # noqa: BLE001 - detection is advisory, must not block connect
        scopes = result.get("scopes") or []
        return {
            "kind": "scoped_token" if scopes else "repository_token",
            "can_create": None,
            "create_private": None,
            "can_push_new": None,
            "can_publish": None,
            "writable": [],
            "readonly": [],
            "see_private": None,
            "see_public": None,
            "write_probed_count": 0,
            "write_probe_total": 0,
        }


def _request_json(
    api_url: str,
    path: str,
    token: str,
    *,
    query: Mapping[str, str] | None = None,
) -> tuple[Any, list[str]]:
    url = api_url.rstrip("/") + path
    if query:
        url = url + "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            body = response.read().decode("utf-8")
            scopes = _parse_scopes(response.headers.get("X-OAuth-Scopes", ""))
    except urllib.error.HTTPError as exc:
        raise GitHubMachineVerificationError(
            f"GitHub check failed: {url} returned HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GitHubMachineVerificationError(
            f"GitHub check failed against {url}: {exc}"
        ) from exc
    try:
        payload = json.loads(body) if body else None
    except ValueError as exc:
        raise GitHubMachineVerificationError(
            f"GitHub check returned invalid JSON from {url}"
        ) from exc
    return payload, scopes


def _identity(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or not payload.get("login"):
        raise GitHubMachineVerificationError(
            "GitHub /user response did not include a login"
        )
    return {
        "checked": True,
        "ok": True,
        "login": str(payload["login"]),
        "id": payload.get("id") if isinstance(payload.get("id"), int) else None,
    }


def _access(
    identity: Mapping[str, Any],
    repos: Any,
    orgs: Any,
    *,
    requested_repo: Any = None,
) -> dict[str, Any]:
    repo_items = repos if isinstance(repos, list) else []
    org_items = orgs if isinstance(orgs, list) else []
    repo_names: list[str] = []
    # Per-repo private flag + permissions, kept so capability detection can split
    # public/private and report the writable set without re-fetching /user/repos.
    repo_details: list[dict[str, Any]] = []
    owners = {str(identity.get("login") or "")}
    for repo in repo_items:
        if not isinstance(repo, Mapping):
            continue
        full_name = repo.get("full_name")
        if isinstance(full_name, str) and full_name:
            repo_names.append(full_name)
            permissions = repo.get("permissions")
            repo_details.append({
                "full_name": full_name,
                "private": bool(repo.get("private")),
                "permissions": dict(permissions)
                if isinstance(permissions, Mapping)
                else {},
            })
        owner = repo.get("owner")
        if isinstance(owner, Mapping) and owner.get("login"):
            owners.add(str(owner["login"]))
    for org in org_items:
        if isinstance(org, Mapping) and org.get("login"):
            owners.add(str(org["login"]))
    access: dict[str, Any] = {
        "owners": sorted(owner for owner in owners if owner),
        "repos": sorted(repo_names),
        "repo_details": sorted(repo_details, key=lambda row: row["full_name"]),
        "repo_count": len(repo_names),
        "repo_listing_ok": isinstance(repos, list),
        "org_listing_ok": isinstance(orgs, list),
    }
    if requested_repo is not None:
        access["requested_repo"] = _repo_summary(requested_repo)
    return access


def _repo_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or not payload.get("full_name"):
        raise GitHubMachineVerificationError(
            "GitHub repo response did not include full_name"
        )
    permissions = payload.get("permissions")
    return {
        "ok": True,
        "full_name": str(payload["full_name"]),
        "private": bool(payload.get("private")),
        "permissions": dict(permissions) if isinstance(permissions, Mapping) else {},
    }


def _repo_path(github_repo: str) -> str:
    parts = github_repo.strip().split("/")
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise GitHubMachineVerificationError("GitHub repo must be OWNER/REPO")
    owner = urllib.parse.quote(parts[0].strip(), safe="")
    repo = urllib.parse.quote(parts[1].strip(), safe="")
    return f"/repos/{owner}/{repo}"


def _parse_scopes(raw: str) -> list[str]:
    return sorted(part.strip() for part in raw.split(",") if part.strip())


def _verify_permission_contract(
    api_url: str,
    token: str,
    identity: Mapping[str, Any],
    access: Mapping[str, Any],
    scopes: list[str],
) -> dict[str, Any]:
    if scopes:
        evaluation = user_token_contract.evaluate_scoped_token_scopes(scopes)
        if evaluation["ok"]:
            return {
                **evaluation,
                "create_repos": user_token_contract.scoped_token_can_create_repos(scopes),
                "summary": (
                    "required GitHub credential scopes include "
                    + ", ".join(user_token_contract.scoped_token_scope_lines())
                ),
            }
        missing = ", ".join(str(scope) for scope in evaluation["missing"])
        raise GitHubMachineVerificationError(
            "GitHub credential is valid"
            f" for {identity.get('login')}, but it is missing required"
            f" GitHub credential scope(s): {missing}. Enable those scopes, or"
            " reconnect through the Yoke GitHub App with "
            f"{user_token_contract.repository_permission_sentence()}."
        )
    repo_full_name = _probe_repo_name(access)
    if repo_full_name:
        try:
            repository_token = github_machine_repository_token.verify_read_access(
                api_url,
                token,
                identity,
                repo_full_name,
                request_json=_request_json,
            )
        except github_machine_repository_token.RepositoryTokenVerificationError as exc:
            raise GitHubMachineVerificationError(str(exc)) from exc
        # Repository-scoped user tokens expose no create grant via API, so create
        # capability is honestly unknown rather than asserted either way.
        repository_token["create_repos"] = {
            "can_create": None,
            "create_private": None,
            "basis": "repository_token_undetectable",
        }
        return repository_token
    raise GitHubMachineVerificationError(
        "GitHub accepted this token, but it did not expose scopes or any "
        "accessible repositories to smoke-test. Enable repository access plus "
        f"{user_token_contract.repository_permission_sentence()}, then retry."
    )


def _probe_repo_name(access: Mapping[str, Any]) -> str | None:
    requested_repo = access.get("requested_repo")
    if isinstance(requested_repo, Mapping) and requested_repo.get("full_name"):
        return str(requested_repo["full_name"])
    repos = access.get("repos")
    if isinstance(repos, list):
        for repo in repos:
            if isinstance(repo, str) and repo.strip():
                return repo.strip()
    return None


__all__ = ["GitHubMachineVerificationError", "verify"]
