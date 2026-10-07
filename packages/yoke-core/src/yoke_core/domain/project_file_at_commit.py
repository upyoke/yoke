"""Read one file of a registered project exactly as one commit holds it.

A control plane may hold a checkout of the project (a local universe) or
none at all (a hosted one), so this asks this machine's registered checkout
first and the project's own authorized repository binding second — the same
preference order carried-work attribution uses. Either answers the same
question about an immutable commit, so the first answer is the answer.
"""

from __future__ import annotations

import base64
import subprocess
from typing import Any, Mapping

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
)


class ProjectFileAbsent(LookupError):
    """The commit does not carry the file."""


class ProjectFileUnreadable(RuntimeError):
    """No source on this host could read the commit."""


def _from_checkout(checkout: str, sha: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", checkout, "show", f"{sha}:{path}"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    probe = subprocess.run(
        ["git", "-C", checkout, "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if probe.returncode == 0:
        raise ProjectFileAbsent(f"commit {sha} does not carry {path}")
    raise ProjectFileUnreadable(f"checkout {checkout} cannot read {sha}: {stderr}")


def _from_provider(conn: Any, project_id: int, sha: str, path: str) -> bytes:
    from yoke_core.domain.function_target_row_project import slug_for_project_id
    from yoke_core.domain.gh_rest_transport import RestRequest, request_with_retry
    from yoke_core.domain.gh_rest_transport_errors import (
        RestNotFoundError,
        RestTransportError,
    )
    from yoke_core.domain.project_github_auth import (
        ProjectGithubAuthError,
        resolve_project_github_auth,
    )

    try:
        auth = resolve_project_github_auth(
            slug_for_project_id(conn, int(project_id)),
            conn=conn,
            required_permissions=GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError as exc:
        raise ProjectFileUnreadable(
            f"the project's GitHub binding cannot read repository contents: {exc}"
        ) from exc
    request = RestRequest(
        method="GET",
        path=f"/repos/{auth.repo}/contents/{path}",
        query={"ref": sha},
    )
    try:
        body = request_with_retry(request, token=auth.token).body
    except RestNotFoundError as exc:
        # GitHub answers 404 both for a missing path and for an unpushed commit.
        raise ProjectFileAbsent(
            f"{auth.repo} has no {path} at {sha} (or that commit is not pushed)"
        ) from exc
    except RestTransportError as exc:
        raise ProjectFileUnreadable(
            f"GitHub could not serve {path} at {sha}: {exc}"
        ) from exc
    if not isinstance(body, Mapping) or body.get("encoding") != "base64":
        raise ProjectFileUnreadable(f"{path} at {sha} is not one file")
    return base64.b64decode(str(body.get("content") or ""))


def read_project_file(conn: Any, project_id: int, sha: str, path: str) -> bytes:
    """``path`` at ``sha``; raises ``ProjectFileAbsent`` or ``ProjectFileUnreadable``."""
    from yoke_core.domain.project_checkout_locations import checkout_for_project_id

    reasons: list[str] = []
    checkout = checkout_for_project_id(int(project_id))
    if checkout is not None:
        try:
            return _from_checkout(str(checkout), sha, path)
        except ProjectFileUnreadable as exc:
            reasons.append(str(exc))
    else:
        reasons.append("no checkout of this project is registered on this host")
    try:
        return _from_provider(conn, project_id, sha, path)
    except ProjectFileUnreadable as exc:
        reasons.append(str(exc))
    raise ProjectFileUnreadable("; ".join(reasons))


__all__ = ["ProjectFileAbsent", "ProjectFileUnreadable", "read_project_file"]
