"""The named outcomes of publishing an install commit, and how they read.

Publication has exactly one job the operator cares about: either the
generated layer reached the remote, or it did not and they need to know what
to do. Every outcome name, refusal classification, recovery recipe, and
operator-facing line lives here so no caller can invent a quieter wording for
"installed but not published".
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from yoke_cli.config.project_publish_request import is_push_denied
from yoke_cli.project_install import checkout_gate

PUBLISHED = "published"
PULL_REQUEST_OPEN = "pull_request_open"
PENDING = "publication_pending"
SKIPPED = "skipped"
ALREADY_PUBLISHED = "already_published"
ELIGIBLE = "eligible"

LOCAL_ONLY_REASON = "local-only checkout: no git remote to publish to"
DISABLED_REASON = "--no-publish"
SOURCE_DEV_REASON = (
    "source-dev/admin local-source apply publishes nothing by design"
)

PROTECTED = "protected"
STALE = "stale"
DENIED = "denied"
FAILED = "failed"

# Protection is claimed only by language that names it. Git appends
# "pre-receive hook declined" to EVERY server-side hook rejection, including a
# plain permission denial, so matching that would route a credentials problem
# down the review path and bury the real cause.
_PROTECTED_SIGNATURES = (
    "gh006",
    "protected branch",
    "must be made through a pull request",
    "required status check",
)
_STALE_SIGNATURES = ("non-fast-forward", "fetch first", "stale info")


def classify_push_failure(detail: str) -> str:
    """Name why the remote refused the push, from what it said."""
    lowered = str(detail or "").lower()
    if any(signature in lowered for signature in _PROTECTED_SIGNATURES):
        return PROTECTED
    if any(signature in lowered for signature in _STALE_SIGNATURES):
        return STALE
    if is_push_denied(lowered):
        return DENIED
    return FAILED


def push_recovery(failure: str, *, remote: str, branch: str) -> str:
    """The command the operator runs to finish a publication that did not."""
    if failure == DENIED:
        return (
            f"this machine's Git credentials may not push to {remote}. "
            f"recipe: authorize the remote, then `git push {remote} {branch}`"
        )
    return (
        "the push did not land. recipe: fix the reported cause, then "
        f"`git push {remote} {branch}`"
    )


def pending(
    repo_root: Path,
    *,
    remote: str,
    branch: str,
    detail: str,
    recovery: str,
    proposal_branch: str | None = None,
) -> dict[str, Any]:
    """The layer is committed here and absent there — say both, plus the fix."""
    return {
        "status": PENDING,
        "remote": remote,
        "branch": branch,
        "commit": head(repo_root),
        "detail": detail,
        "recovery": recovery,
        **({"proposal_branch": proposal_branch} if proposal_branch else {}),
    }


def already_published(
    *, remote: str, branch: str, commit: str, detail: str = "",
) -> dict[str, Any]:
    return {
        "status": ALREADY_PUBLISHED,
        "remote": remote,
        "branch": branch,
        "commit": commit,
        **({"detail": detail} if detail else {}),
    }


def with_reconcile(
    outcome: dict[str, Any], reconciled: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep the reconcile record beside the outcome it produced."""
    if reconciled is None:
        return outcome
    return {**outcome, "reconcile": reconciled}


def head(repo_root: Path) -> str:
    return checkout_gate.run_git(repo_root, "rev-parse", "HEAD").stdout.strip()


def is_publication_pending(report: dict[str, Any] | None) -> bool:
    """True when the layer is installed locally but not on the remote yet."""
    publication = (report or {}).get("publication")
    if not isinstance(publication, dict):
        return False
    return publication.get("status") in (PENDING, PULL_REQUEST_OPEN)


def announce(report: dict[str, Any] | None) -> None:
    """Print the publication outcome where the operator will actually see it."""
    publication = (report or {}).get("publication")
    if not isinstance(publication, dict):
        return
    status = str(publication.get("status") or "")
    target = f"{publication.get('remote')}/{publication.get('branch')}"
    if status in (PUBLISHED, ALREADY_PUBLISHED):
        print(f"yoke project publish: {status} to {target}", file=sys.stderr)
        return
    if status == SKIPPED:
        print(
            f"yoke project publish: skipped ({publication.get('reason')})",
            file=sys.stderr,
        )
        return
    headline = (
        "INSTALLED LOCALLY, PROPOSED FOR REVIEW"
        if status == PULL_REQUEST_OPEN
        else "INSTALLED LOCALLY, NOT PUBLISHED"
    )
    print(
        f"yoke project publish: {headline}\n"
        f"  commit:   {publication.get('commit')}\n"
        f"  target:   {target}\n"
        f"  detail:   {publication.get('detail')}\n"
        f"  recovery: {publication.get('recovery')}",
        file=sys.stderr,
    )


__all__ = [
    "ALREADY_PUBLISHED",
    "DENIED",
    "DISABLED_REASON",
    "ELIGIBLE",
    "FAILED",
    "LOCAL_ONLY_REASON",
    "PENDING",
    "PROTECTED",
    "PUBLISHED",
    "PULL_REQUEST_OPEN",
    "SKIPPED",
    "SOURCE_DEV_REASON",
    "STALE",
    "already_published",
    "announce",
    "classify_push_failure",
    "head",
    "is_publication_pending",
    "pending",
    "push_recovery",
    "with_reconcile",
]
