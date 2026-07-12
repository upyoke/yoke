"""Repository and owner discovery for GitHub publishing."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from yoke_cli.config.github_publish_transport import GitHubPublishError
from yoke_contracts import github_origin

_USER_PATH = "/user"
_ORGS_PATH = "/user/orgs"
_USER_REPOS_PATH = "/user/repos"
_ACCOUNT_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
OWNER_LIST_DEADLINE_SECONDS = 20.0


@dataclass(frozen=True)
class RepoOwner:
    """One account a token can create repos under."""

    login: str
    # "user" for the authenticated account, "organization" for an org.
    kind: str


@dataclass(frozen=True)
class RepoRef:
    """One repository the token can reach, for the clone-from-GitHub picker."""

    full_name: str
    clone_url: str
    private: bool


def list_user_repos(
    request_json: Callable[..., Any],
    api_url: str,
    token: str,
    *,
    private_only: bool = False,
    page_size: int = 50,
    web_url: str = github_origin.DEFAULT_GITHUB_WEB_URL,
) -> list[RepoRef]:
    """List repos the token can reach, most-recently-pushed first."""

    page_size = max(1, min(int(page_size), 100))
    payload = request_json(
        api_url,
        _USER_REPOS_PATH,
        token,
        query={
            "per_page": str(page_size),
            "sort": "pushed",
            "affiliation": "owner,collaborator,organization_member",
        },
    )
    try:
        endpoint = github_origin.validate_github_web_endpoint(web_url)
    except github_origin.GitHubApiOriginError as exc:
        raise GitHubPublishError(str(exc)) from exc
    refs: list[RepoRef] = []
    for repo in payload if isinstance(payload, list) else []:
        if not isinstance(repo, Mapping):
            continue
        full_name = repo.get("full_name")
        clone_url = repo.get("clone_url")
        if not (isinstance(full_name, str) and full_name):
            continue
        if not (isinstance(clone_url, str) and clone_url):
            continue
        if any(ord(character) < 32 or ord(character) == 127 for character in full_name):
            continue
        private = repo.get("private")
        if not isinstance(private, bool):
            continue
        try:
            named_repo = github_origin.normalize_github_repository(
                full_name,
                web_url=endpoint.base_url,
            )
            cloned_repo = github_origin.normalize_github_repository(
                clone_url,
                web_url=endpoint.base_url,
            )
        except github_origin.GitHubApiOriginError:
            continue
        if named_repo.casefold() != cloned_repo.casefold():
            continue
        if private_only and not private:
            continue
        refs.append(
            RepoRef(
                full_name=named_repo,
                clone_url=endpoint.url(f"/{named_repo}.git"),
                private=private,
            )
        )
    return refs


def list_repo_owners(
    request_json: Callable[..., Any],
    api_url: str,
    token: str,
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> list[RepoOwner]:
    """Return the authenticated user plus every org the token can see."""

    deadline = monotonic() + OWNER_LIST_DEADLINE_SECONDS
    user = request_json(
        api_url,
        _USER_PATH,
        token,
        deadline=deadline,
        monotonic=monotonic,
    )
    if not isinstance(user, Mapping):
        raise GitHubPublishError("GitHub /user response did not include a login")
    user_login = _validated_account_login(user.get("login"))
    if user_login is None:
        raise GitHubPublishError(
            "GitHub /user response did not include a valid account login"
        )
    owners = [RepoOwner(login=user_login, kind="user")]
    seen = {user_login.casefold(): "user"}
    for page in range(1, 11):
        orgs = request_json(
            api_url,
            _ORGS_PATH,
            token,
            query={"per_page": "100", "page": str(page)},
            deadline=deadline,
            monotonic=monotonic,
        )
        if not isinstance(orgs, list):
            raise GitHubPublishError(
                "GitHub organization response did not contain a list"
            )
        for org in orgs:
            login = _validated_account_login(
                org.get("login") if isinstance(org, Mapping) else None
            )
            if login is None:
                continue
            key = login.casefold()
            prior_kind = seen.get(key)
            if prior_kind == "user":
                raise GitHubPublishError(
                    "GitHub owner response assigned one account both user and "
                    "organization kinds"
                )
            if prior_kind:
                continue
            seen[key] = "organization"
            owners.append(RepoOwner(login=login, kind="organization"))
        if len(orgs) < 100:
            break
    return owners


def _validated_account_login(value: Any) -> str | None:
    if not isinstance(value, str) or not _ACCOUNT_LOGIN.fullmatch(value):
        return None
    return value
