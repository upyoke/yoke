"""Typed GitHub REST API surface — umbrella + shared types.

This module family (``github_rest`` + ``github_rest_issues``,
``github_rest_labels``, ``github_rest_comments``, ``github_rest_sub_issues``,
``github_rest_graphql``) is Yoke's canonical surface for talking to
GitHub. Yoke does NOT use the ``gh`` CLI; all GitHub access is
PAT-backed REST through :mod:`yoke_core.domain.gh_rest_transport`.

The split mirrors the ``backlog_github_*`` and ``epic_task_sync_github_*``
file families: one umbrella defining shared dataclasses and the
per-project ``resolve_target`` helper, and per-resource submodules
hosting the typed functions for each REST endpoint family. Each file
stays under the 350-line cap.

Re-exports the per-resource public functions so callers can write a
single ``from yoke_core.domain.github_rest import create_issue,
list_labels, ...``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from yoke_core.domain import gh_rest_transport as _transport
from yoke_core.domain.gh_rest_transport import (
    RateLimitedError,
    RestAuthError,
    RestNotFoundError,
    RestServerError,
    RestTransportError,
    RestUnprocessableError,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuth,
    ProjectGithubAuthError,
    resolve_project_github_auth,
)


# ---------------------------------------------------------------------------
# Shared dataclasses — every typed function returns one of these (or a list).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    """A single GitHub issue (or pull request — GitHub treats them the same)."""

    number: int
    title: str
    state: str  # "OPEN" | "CLOSED" (uppercase, normalised from the API)
    body: str = ""
    labels: tuple[str, ...] = ()
    html_url: str = ""
    user_login: str = ""


@dataclass(frozen=True)
class Label:
    """A repository label."""

    name: str
    color: str = ""
    description: str = ""


@dataclass(frozen=True)
class Comment:
    """A single issue comment."""

    id: int
    body: str
    html_url: str = ""
    user_login: str = ""


@dataclass(frozen=True)
class Target:
    """Resolved per-project REST target: owner, repo, token, raw repo string.

    Callers shouldn't carry the ``owner``/``repo`` split themselves;
    :func:`resolve_target` returns this bundle so each typed function call
    builds its REST path from a single typed object.
    """

    project: str
    owner: str
    repo: str
    token: str
    repo_slug: str = ""  # "owner/repo" — convenience for log lines

    @classmethod
    def from_auth(cls, auth: ProjectGithubAuth) -> "Target":
        owner, repo = _transport.split_repo(auth.repo)
        return cls(
            project=auth.project, owner=owner, repo=repo,
            token=auth.token, repo_slug=auth.repo,
        )


def resolve_target(
    project: str, *, db_path: str | None = None,
) -> Target:
    """Resolve the typed REST target for a project (auth + owner/repo split).

    Wraps :func:`resolve_project_github_auth` so the per-resource modules
    accept a project string and don't have to thread auth themselves.
    Raises :class:`ProjectGithubAuthError` when the project has no
    usable token / repo metadata — callers handle that as a hard auth
    failure (Yoke-control-plane fail-closed; non-Yoke projects
    fail-soft in the resync sweep layer).
    """
    auth = resolve_project_github_auth(project, db_path=db_path)
    return Target.from_auth(auth)


# ---------------------------------------------------------------------------
# Re-export per-resource public functions so callers can import from the
# umbrella. Submodule imports happen at the bottom to avoid circular
# binding during module init (each submodule imports types from here).
# ---------------------------------------------------------------------------


__all__ = [
    # Types
    "Issue", "Label", "Comment", "Target",
    # Transport exceptions (re-exported for convenience — callers handling
    # multiple GitHub error classes import from one place)
    "RateLimitedError", "RestAuthError", "RestNotFoundError",
    "RestServerError", "RestTransportError", "RestUnprocessableError",
    "ProjectGithubAuthError",
    # Resolver
    "resolve_target",
    # Issue family
    "create_issue", "update_issue", "set_issue_state",
    "get_issue", "list_issues", "delete_issue",
    # Label family
    "list_labels", "create_label", "add_labels", "remove_labels",
    # Comment family
    "post_comment", "list_comments",
    # Sub-issue family
    "add_sub_issue",
    # GraphQL
    "graphql_query",
]


from yoke_core.domain.github_rest_issues import (  # noqa: E402
    create_issue, update_issue, set_issue_state,
    get_issue, list_issues, delete_issue,
)
from yoke_core.domain.github_rest_labels import (  # noqa: E402
    list_labels, create_label, add_labels, remove_labels,
)
from yoke_core.domain.github_rest_comments import (  # noqa: E402
    post_comment, list_comments,
)
from yoke_core.domain.github_rest_sub_issues import (  # noqa: E402
    add_sub_issue,
)
from yoke_core.domain.github_rest_graphql import (  # noqa: E402
    graphql_query,
)
