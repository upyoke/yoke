"""Detect what a GitHub user token can actually do for onboarding.

GitHub can report per-repo ``permissions`` as the owner role rather than the
token grant, so this detector uses non-mutating probes for the capabilities the
onboarding flow needs. Each probe exploits GitHub's auth-before-validation order:
it sends a deliberately invalid body so nothing can ever be created, then reads
the HTTP status the permission gate returns before body validation.

  * Create probe: ``POST /user/repos`` with ``{"name": ""}``. An empty name can
    never create a repo. 422 => the token passed the create gate; 403 => it did
    not.
  * Write probe: ``PUT /repos/{owner}/{repo}/contents/<probe-path>`` with ``{}``
    (missing the required ``message``/``content``, so it writes nothing). 422 =>
    contents:write is granted on that repo; 403 => it is not.

Scope-bearing tokens report grants through X-OAuth-Scopes, so that branch needs
no probes. Every probe failure or timeout yields UNKNOWN (None) and never raises
into the connect flow.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Mapping, Optional

from yoke_contracts import github_user_token_permissions as user_token_contract

_TIMEOUT_S = 20.0
_CREATE_PROBE_PATH = "/user/repos"
_WRITE_PROBE_FILE = ".yoke-capability-probe"
_PROBE_CAN = 422  # passed the permission gate, failed body validation
_PROBE_CANNOT = 403  # blocked at the permission gate
# How many repos each repository-token probe samples. Public probes confirm
# "all repositories" access (a non-granted public repo writable => broad grant);
# private probes confirm the per-repo writable set the picker would offer.
_PUBLIC_WRITE_SAMPLE = 3
# Each private repo costs one write-probe API call (GitHub's per-repo permissions
# field may not show token grants), so the write set is a bounded sample. The
# connect screen tells the user how many of their repos were actually checked.
_PRIVATE_WRITE_SAMPLE = 25
# Bound the displayed writable/readonly lists; the connect screen is fixed-width.
_DISPLAY_LIST_CAP = 8


def _request_status(
    api_url: str,
    path: str,
    token: str,
    *,
    method: str,
    body: Mapping[str, Any] | None,
) -> Optional[int]:
    """Issue one request and return its HTTP status code (None on network error).

    The default network seam. Tests patch ``probe_status`` (or pass their own
    ``request_status``) so no probe ever reaches real GitHub.
    """
    url = api_url.rstrip("/") + path
    data = json.dumps(dict(body or {})).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def probe_status(
    api_url: str,
    path: str,
    token: str,
    *,
    method: str,
    body: Mapping[str, Any] | None,
    request_status=_request_status,
) -> Optional[int]:
    """Return the HTTP status for one probe, never raising into the caller."""
    try:
        return request_status(api_url, path, token, method=method, body=body)
    except Exception:  # noqa: BLE001 - a probe must never break the connect flow
        return None


def _status_to_capability(status: Optional[int]) -> Optional[bool]:
    if status == _PROBE_CAN:
        return True
    if status == _PROBE_CANNOT:
        return False
    return None


def can_create_repo(
    api_url: str,
    token: str,
    *,
    request_status=_request_status,
) -> Optional[bool]:
    """Run the create probe: 422 -> can create, 403 -> cannot, else unknown."""
    status = probe_status(
        api_url,
        _CREATE_PROBE_PATH,
        token,
        method="POST",
        body={"name": ""},
        request_status=request_status,
    )
    return _status_to_capability(status)


def can_write_repo(
    api_url: str,
    token: str,
    repo: str,
    *,
    request_status=_request_status,
) -> Optional[bool]:
    """Run the write probe on ``repo``: 422 -> writable, 403 -> not, else unknown."""
    status = probe_status(
        api_url,
        f"/repos/{repo}/contents/{_WRITE_PROBE_FILE}",
        token,
        method="PUT",
        body={},
        request_status=request_status,
    )
    return _status_to_capability(status)


def _repo_details(verification: Mapping[str, Any]) -> list[dict[str, Any]]:
    access = verification.get("access")
    if not isinstance(access, Mapping):
        return []
    details = access.get("repo_details")
    rows: list[dict[str, Any]] = []
    if isinstance(details, list):
        for entry in details:
            if isinstance(entry, Mapping) and entry.get("full_name"):
                rows.append({
                    "full_name": str(entry["full_name"]),
                    "private": bool(entry.get("private")),
                    "permissions": entry.get("permissions")
                    if isinstance(entry.get("permissions"), Mapping)
                    else {},
                })
        return rows
    # Fall back to the bare name list when no per-repo detail was surfaced.
    repos = access.get("repos")
    if isinstance(repos, list):
        for name in repos:
            if isinstance(name, str) and name.strip():
                rows.append({"full_name": name.strip(), "private": False,
                             "permissions": {}})
    return rows


def _scoped_token_writable(details: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Split repos into writable/readonly by the real per-repo push flag."""
    writable: list[str] = []
    readonly: list[str] = []
    for repo in details:
        perms = repo["permissions"]
        can_push = bool(
            perms.get("push") or perms.get("admin") or perms.get("maintain")
        )
        (writable if can_push else readonly).append(repo["full_name"])
    return writable, readonly


def _detect_scoped_token(
    scopes: list[str],
    details: list[dict[str, Any]],
    see_private: int,
    see_public: int,
) -> dict[str, Any]:
    create = user_token_contract.scoped_token_can_create_repos(scopes)
    can_create = bool(create["can_create"])
    writable, readonly = _scoped_token_writable(details)
    return {
        "kind": "scoped_token",
        "can_create": can_create,
        "create_private": bool(create["create_private"]),
        # A repo/public_repo-scoped token can push to repos it creates.
        "can_push_new": can_create,
        "can_publish": can_create,
        "writable": writable[:_DISPLAY_LIST_CAP],
        # Cap the display list like the repository-token branch; the true size lives
        # in readonly_count so the "except" summary can count the remainder.
        "readonly": readonly[:_DISPLAY_LIST_CAP],
        "writable_count": len(writable),
        "readonly_count": len(readonly),
        "see_private": see_private,
        "see_public": see_public,
        "write_probed_count": 0,
        "write_probe_total": 0,
    }


def _any_true(results: list[Optional[bool]]) -> Optional[bool]:
    """True if any probe says yes; False if all say no; None if all unknown."""
    if any(result is True for result in results):
        return True
    if any(result is False for result in results):
        return False
    return None


def _detect_repository_token(
    api_url: str,
    token: str,
    details: list[dict[str, Any]],
    see_private: int,
    see_public: int,
    *,
    request_status,
) -> dict[str, Any]:
    can_create = can_create_repo(api_url, token, request_status=request_status)
    public = [r["full_name"] for r in details if not r["private"]]
    private = [r["full_name"] for r in details if r["private"]]
    # Pushing to a brand-new repo only works for an "all repositories" grant; a
    # writable non-granted public repo is the cheap, safe proof of that breadth.
    push_new = _any_true([
        can_write_repo(api_url, token, repo, request_status=request_status)
        for repo in public[:_PUBLIC_WRITE_SAMPLE]
    ]) if public else None
    writable: list[str] = []
    readonly: list[str] = list(public)
    probed = 0
    for repo in private[:_PRIVATE_WRITE_SAMPLE]:
        probed += 1
        if can_write_repo(api_url, token, repo, request_status=request_status):
            writable.append(repo)
        else:
            readonly.append(repo)
    readonly.extend(private[_PRIVATE_WRITE_SAMPLE:])
    return {
        "kind": "repository_token",
        "can_create": can_create,
        "create_private": None,
        "can_push_new": push_new,
        "can_publish": bool(can_create) and bool(push_new),
        "writable": writable[:_DISPLAY_LIST_CAP],
        "readonly": readonly[:_DISPLAY_LIST_CAP],
        "writable_count": len(writable),
        "readonly_count": len(readonly),
        "see_private": see_private,
        "see_public": see_public,
        "write_probed_count": probed,
        "write_probe_total": len(private),
    }


def detect_capability(
    api_url: str,
    token: str,
    verification: Mapping[str, Any],
    *,
    request_status=_request_status,
) -> dict[str, Any]:
    """Report precisely what ``token`` can and cannot do.

    Scope-bearing tokens derive from X-OAuth-Scopes (no probes). Repository
    tokens probe create + write, since GitHub's reported per-repo permissions
    may be the owner's role rather than the token grant.
    """
    scopes = [str(s) for s in verification.get("scopes") or [] if str(s)]
    details = _repo_details(verification)
    see_private = sum(1 for repo in details if repo["private"])
    see_public = sum(1 for repo in details if not repo["private"])
    if scopes:
        return _detect_scoped_token(scopes, details, see_private, see_public)
    return _detect_repository_token(
        api_url, token, details, see_private, see_public,
        request_status=request_status,
    )


__all__ = [
    "can_create_repo",
    "can_write_repo",
    "detect_capability",
    "probe_status",
]
