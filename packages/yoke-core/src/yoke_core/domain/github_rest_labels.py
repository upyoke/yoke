"""Typed GitHub REST surface — label family.

Functions cover the per-repo label catalogue + the per-issue add/remove
operations. All kwargs are typed; all responses parse into typed
:class:`yoke_core.domain.github_rest.Label` dataclasses or plain
strings for label-name reads.

Owner: re-exported from :mod:`yoke_core.domain.github_rest`.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestRequest,
    RestUnprocessableError,
    quote_path_segment,
    request_with_retry,
)


def _parse_label(payload: Any):
    """Parse a single GitHub /labels payload into a Label dataclass."""
    from yoke_core.domain.github_rest import Label

    if not isinstance(payload, dict):
        raise ValueError(f"unexpected GitHub label payload shape: {type(payload).__name__}")
    return Label(
        name=str(payload.get("name", "")),
        color=str(payload.get("color", "")),
        description=str(payload.get("description") or ""),
    )


def _target_for(project: str, *, db_path: Optional[str] = None):
    from yoke_core.domain.github_rest import resolve_target

    return resolve_target(project, db_path=db_path)


def list_labels(
    *, project: str, limit: int = 100,
    db_path: Optional[str] = None,
) -> list:
    """GET /repos/{owner}/{repo}/labels. Returns list of Label."""
    tgt = _target_for(project, db_path=db_path)
    items: list[Any] = []
    page = 1
    per_page = min(100, max(1, limit))
    while len(items) < limit:
        resp = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{tgt.owner}/{tgt.repo}/labels",
                query={"per_page": str(per_page), "page": str(page)},
            ),
            token=tgt.token,
        )
        batch = resp.body if isinstance(resp.body, list) else []
        if not batch:
            break
        items.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    items = items[:limit]
    return [_parse_label(item) for item in items if isinstance(item, dict)]


def create_label(
    *, project: str, name: str, color: str = "ededed",
    description: str = "", db_path: Optional[str] = None,
):
    """POST /repos/{owner}/{repo}/labels. Returns the typed Label.

    Idempotent in spirit: GitHub returns 422 (already exists) when the
    label is already present, which :class:`RestUnprocessableError`
    surfaces typed for the caller to ignore or rewrite.
    """
    tgt = _target_for(project, db_path=db_path)
    payload: dict[str, Any] = {"name": name, "color": color}
    if description:
        payload["description"] = description
    resp = request_with_retry(
        RestRequest(
            method="POST",
            path=f"/repos/{tgt.owner}/{tgt.repo}/labels",
            body=payload,
        ),
        token=tgt.token,
    )
    return _parse_label(resp.body)


def add_labels(
    *, project: str, number: int, labels: Sequence[str],
    db_path: Optional[str] = None,
) -> list[str]:
    """POST /repos/{owner}/{repo}/issues/{number}/labels.

    Adds (does not replace) labels on the issue. Returns the resulting
    label name list as plain strings.
    """
    if not labels:
        return []
    tgt = _target_for(project, db_path=db_path)
    resp = request_with_retry(
        RestRequest(
            method="POST",
            path=f"/repos/{tgt.owner}/{tgt.repo}/issues/{number}/labels",
            body={"labels": list(labels)},
        ),
        token=tgt.token,
    )
    return _extract_label_names(resp.body)


def remove_labels(
    *, project: str, number: int, labels: Sequence[str],
    db_path: Optional[str] = None,
) -> list[str]:
    """DELETE labels from an issue.

    Removes each label individually so a partial-success run leaves
    the others removed. A 404 on any single label is silently ignored
    (label was already absent). Returns the final label name list.
    """
    if not labels:
        return _current_label_names(project=project, number=number, db_path=db_path)
    tgt = _target_for(project, db_path=db_path)
    for label in labels:
        try:
            request_with_retry(
                RestRequest(
                    method="DELETE",
                    path=(
                        f"/repos/{tgt.owner}/{tgt.repo}/issues/{number}/labels/"
                        f"{quote_path_segment(label)}"
                    ),
                ),
                token=tgt.token,
            )
        except RestNotFoundError:
            continue
    return _current_label_names(project=project, number=number, db_path=db_path)


def _current_label_names(
    *, project: str, number: int, db_path: Optional[str] = None,
) -> list[str]:
    tgt = _target_for(project, db_path=db_path)
    resp = request_with_retry(
        RestRequest(
            method="GET",
            path=f"/repos/{tgt.owner}/{tgt.repo}/issues/{number}/labels",
        ),
        token=tgt.token,
    )
    return _extract_label_names(resp.body)


def _extract_label_names(payload: Any) -> list[str]:
    if not isinstance(payload, list):
        return []
    names: list[str] = []
    for item in payload:
        if isinstance(item, dict) and item.get("name") is not None:
            names.append(str(item["name"]))
    return names


__all__ = [
    "list_labels", "create_label", "add_labels", "remove_labels",
]
