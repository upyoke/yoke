"""REST-backed label helpers for the backlog sync chain.

Exports the three public helpers — :func:`add_labels`,
:func:`remove_label`, :func:`set_labels` — plus the shared private
helpers callers reach for (issue-label fetch, issue state fetch,
repo-label projection, and the label-create idempotent wrapper). All
operations route through :mod:`yoke_core.domain.gh_rest_transport`
and surface typed :class:`RestTransportError` subclasses (notably
:class:`RestAuthError` carrying actionable scope hints on 403).
"""

from __future__ import annotations

from typing import Iterable, Optional

from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestRequest,
    RestTransportError,
    RestUnprocessableError,
    quote_path_segment,
    request_with_retry,
    split_repo,
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def add_labels(
    repo: str, issue_number: int, labels: Iterable[str], *, token: str,
    timeout_seconds: Optional[float] = None,
    max_attempts: Optional[int] = None,
) -> None:
    """POST ``/repos/{o}/{n}/issues/{issue_number}/labels`` with ``labels``.

    Accepts a typed sequence rather than a comma-joined string. Empty
    ``labels`` is a no-op. ``RestTransportError`` subclasses propagate
    verbatim so callers branch on the typed class.
    """
    cleaned = [label.strip() for label in labels if label and label.strip()]
    if not cleaned:
        return
    owner, name = split_repo(repo)
    request_with_retry(
        RestRequest(
            method="POST",
            path=f"/repos/{owner}/{name}/issues/{int(issue_number)}/labels",
            body={"labels": cleaned},
        ),
        token=token,
        **_transport_budget_kwargs(timeout_seconds, max_attempts),
    )


def remove_label(
    repo: str, issue_number: int, label: str, *, token: str,
    timeout_seconds: Optional[float] = None,
    max_attempts: Optional[int] = None,
) -> None:
    """DELETE ``/repos/{o}/{n}/issues/{issue_number}/labels/{label}``.

    A :class:`RestNotFoundError` (label not present on the issue) is
    swallowed — the operation is idempotent. Other
    :class:`RestTransportError` subclasses propagate.
    """
    label_clean = (label or "").strip()
    if not label_clean:
        return
    owner, name = split_repo(repo)
    try:
        request_with_retry(
            RestRequest(
                method="DELETE",
                path=(
                    f"/repos/{owner}/{name}/issues/{int(issue_number)}/"
                    f"labels/{quote_path_segment(label_clean)}"
                ),
            ),
            token=token,
            **_transport_budget_kwargs(timeout_seconds, max_attempts),
        )
    except RestNotFoundError:
        return


def set_labels(
    repo: str, issue_number: int, labels: Iterable[str], *, token: str,
) -> None:
    """PUT ``/repos/{o}/{n}/issues/{issue_number}/labels`` with ``labels``.

    Replaces the issue's label set wholesale — equivalent to a single
    ``add_labels`` after the issue's existing labels have been cleared.
    """
    cleaned = [label.strip() for label in labels if label and label.strip()]
    owner, name = split_repo(repo)
    request_with_retry(
        RestRequest(
            method="PUT",
            path=f"/repos/{owner}/{name}/issues/{int(issue_number)}/labels",
            body={"labels": cleaned},
        ),
        token=token,
    )


# ---------------------------------------------------------------------------
# Supporting reads used by sync_labels / state_sync / done_sync
# ---------------------------------------------------------------------------


def fetch_issue_labels(repo: str, issue_number: int, *, token: str) -> list[str]:
    """Return the current label names attached to ``issue_number``."""
    owner, name = split_repo(repo)
    try:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=(
                    f"/repos/{owner}/{name}/issues/{int(issue_number)}"
                ),
            ),
            token=token,
        )
    except RestTransportError:
        return []
    payload = response.body if isinstance(response.body, dict) else {}
    return [
        str(entry.get("name", "")).strip()
        for entry in payload.get("labels", [])
        if isinstance(entry, dict) and entry.get("name")
    ]


def fetch_issue_state(repo: str, issue_number: int, *, token: str) -> str:
    """Return ``OPEN``/``CLOSED``/``UNKNOWN`` for the issue."""
    owner, name = split_repo(repo)
    try:
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=(
                    f"/repos/{owner}/{name}/issues/{int(issue_number)}"
                ),
            ),
            token=token,
        )
    except RestTransportError:
        return "UNKNOWN"
    payload = response.body if isinstance(response.body, dict) else {}
    return str(payload.get("state", "") or "UNKNOWN").upper()


def fetch_repo_labels(repo: str, *, token: str) -> dict[str, str]:
    """Return ``{name: color}`` for every label currently on ``repo``."""
    owner, name = split_repo(repo)
    response = request_with_retry(
        RestRequest(
            method="GET",
            path=f"/repos/{owner}/{name}/labels",
            query={"per_page": "100"},
        ),
        token=token,
    )
    items = response.body if isinstance(response.body, list) else []
    out: dict[str, str] = {}
    for entry in items:
        if not isinstance(entry, dict):
            continue
        label_name = str(entry.get("name", "")).strip()
        if not label_name:
            continue
        out[label_name] = str(entry.get("color", "")).strip()
    return out


def ensure_label(
    name: str, color: str, repo: str, *, token: str, description: str = "",
    timeout_seconds: Optional[float] = None,
    max_attempts: Optional[int] = None,
) -> None:
    """Idempotently ensure a repo label exists with ``color``/``description``.

    POSTs first; on :class:`RestUnprocessableError` (already exists) the
    helper PATCHes the existing row so the desired color and description
    converge — matching the ``--force`` semantic the old ``gh label
    create --force`` invocation relied on.
    """
    owner, repo_name = split_repo(repo)
    try:
        request_with_retry(
            RestRequest(
                method="POST",
                path=f"/repos/{owner}/{repo_name}/labels",
                body={"name": name, "color": color, "description": description},
            ),
            token=token,
            **_transport_budget_kwargs(timeout_seconds, max_attempts),
        )
    except RestUnprocessableError:
        request_with_retry(
            RestRequest(
                method="PATCH",
                path=f"/repos/{owner}/{repo_name}/labels/{quote_path_segment(name)}",
                body={"color": color, "description": description},
            ),
            token=token,
            **_transport_budget_kwargs(timeout_seconds, max_attempts),
        )


def _transport_budget_kwargs(
    timeout_seconds: Optional[float], max_attempts: Optional[int],
) -> dict[str, object]:
    pairs = (("timeout_seconds", timeout_seconds), ("max_attempts", max_attempts))
    return {name: value for name, value in pairs if value is not None}


__all__ = [
    "add_labels",
    "remove_label",
    "set_labels",
    "fetch_issue_labels",
    "fetch_issue_state",
    "fetch_repo_labels",
    "ensure_label",
]
