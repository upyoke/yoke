"""Who may name a preview occupancy, and who may take one over.

A preview's slug is its occupancy: the deploy directory, the derived port,
the Compose project and the public URL all follow from it. Two previews
resolving to one slug are not two previews — the second one replaces the
first.

That is ordinary and wanted for a branch preview, whose whole point is to
follow its branch. It is exactly what a frozen release preview must never
suffer, because its URL promises that what it serves stays pinned while a
candidate is reviewed against it. The reserved namespace
(:func:`ephemeral_substrate.is_frozen_preview_slug`) is what separates
them, and these are the refusals that make the reservation real on the
paths that could otherwise cross it.
"""

from __future__ import annotations

from yoke_core.domain.deploy_ephemeral_files import EphemeralDeployError
from yoke_core.domain.ephemeral_substrate import (
    is_frozen_preview_slug,
    slugify_branch,
)


def resolve_deploy_occupancy(
    preview_key: str, *, branch: str, revision: str
) -> tuple[str, str]:
    """Return the ``(preview_key, slug)`` one deploy may occupy.

    Resolved before the caller claims either, because a deploy's failure
    path marks whatever slug it holds: refusing a takeover and then stamping
    the frozen preview's own row failed would be a smaller version of the
    same trespass.
    """
    preview_key = preview_key or branch
    if not preview_key:
        raise EphemeralDeployError(
            "[ephemeral] no preview to deploy: run item-bound (the item's "
            "worktree branch) or pass --branch to "
            "python3 -m yoke_core.domain.deploy_ephemeral"
        )
    if not revision and not branch:
        raise EphemeralDeployError(
            f"[ephemeral] preview '{preview_key}' names no branch and no "
            "revision, so there is nothing to resolve a commit from; pass "
            "the exact revision for a preview that is not branch-shaped"
        )
    slug = slugify_branch(preview_key)
    require_unreserved_deploy(preview_key, slug, pinned=bool(revision))
    return preview_key, slug


def require_unreserved_deploy(preview_key: str, slug: str, *, pinned: bool) -> None:
    """Refuse a branch preview that would take over a frozen occupancy.

    *pinned* is what actually makes a preview frozen — a revision the caller
    supplied rather than one resolved from a moving branch. The refusal keys
    on that rather than on the slug's shape, because a release preview
    deploys under exactly that shape and must still work.
    """
    if pinned or not is_frozen_preview_slug(slug):
        return
    raise EphemeralDeployError(
        f"[ephemeral] preview '{preview_key}' resolves to slug '{slug}', "
        "which is reserved for frozen release previews of a pinned "
        "candidate; rename the branch to deploy it as a branch preview"
    )


def require_unreserved_teardown(preview_key: str, slug: str, *, owned: bool) -> None:
    """Refuse a branch-named teardown of a frozen occupancy.

    The same trespass read backwards: a caller naming an occupancy it never
    created would delete the preview a release is still being reviewed
    against. *owned* is the caller saying it is that release.
    """
    if owned or not is_frozen_preview_slug(slug):
        return
    raise EphemeralDeployError(
        f"[ephemeral] preview '{preview_key}' resolves to slug '{slug}', "
        "which is reserved for frozen release previews; tear one down as "
        "the release preview it is, not by branch"
    )


__all__ = [
    "require_unreserved_deploy",
    "require_unreserved_teardown",
    "resolve_deploy_occupancy",
]
