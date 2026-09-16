"""Who may occupy a preview slug, and on whose candidate.

A preview's slug is its occupancy: the deploy directory, the derived port,
the Compose project and the public URL all follow from it. Two previews
resolving to one slug are not two previews — the second replaces the first.

That is ordinary and wanted for a branch preview, whose whole point is to
follow its branch. It is what a frozen release preview must never suffer,
because its URL promises that what it serves stays pinned while a candidate
is reviewed against it. Two things keep them apart.

**One name, two reserved namespaces.** Every frozen preview — whoever
deploys it — is named for its deployment run, so it always lands in the
reserved release-run namespace and a branch never can, because a branch
resolving into that shape is refused before it deploys. Previews published
before run-naming still occupy the earlier hash shape on preview hosts, and
that shape stays reserved for exactly the same reason: nothing new is
published under it, but a branch that could take one would deploy a moving
branch over a candidate somebody is still being shown.

**Ownership is read, not asserted.** That a caller says it holds a frozen
occupancy is not evidence; the recorded preview is. Before a frozen deploy
claims a slug, the stored row for that occupancy has to agree about which
candidate lives there, and a read that fails to answer refuses rather than
assuming the slug is free.
"""

from __future__ import annotations

import re

from yoke_core.domain.deploy_ephemeral_files import EphemeralDeployError
from yoke_core.domain.ephemeral_substrate import (
    is_release_preview_slug,
    require_release_preview_slug,
    slugify_branch,
)

#: The shape release previews were published under before they were named
#: for their run. Yoke never publishes another one, and never addresses an
#: existing one — they are removed on the host by hand — but the shape stays
#: reserved so a branch cannot deploy over or tear down one that is still
#: serving a review.
RETAINED_PREVIEW_SLUG_RE = re.compile(r"^rel-[0-9a-f]{32}$")


def is_reserved_preview_slug(slug: str) -> bool:
    """Whether a branch is forbidden from occupying *slug*.

    Wider than :func:`is_release_preview_slug`, which answers the different
    question of whether a name is one Yoke may publish today.
    """
    return is_release_preview_slug(slug) or bool(
        RETAINED_PREVIEW_SLUG_RE.fullmatch(slug)
    )


def preview_slug(preview_key: str, *, frozen: bool) -> str:
    """The occupancy *preview_key* names, under the rule its kind uses.

    The two rules are deliberately different functions rather than one with
    a flag inside: a branch preview must stay addressable by a name a person
    typed, and a frozen preview must land in a namespace no typed name can
    reach. Sharing a derivation is exactly how the two namespaces met. A
    frozen preview's key already *is* its slug — the deployment run names
    it — so the rule there is to require that shape, not to compute one.
    """
    if frozen:
        return require_release_preview_slug(preview_key)
    return slugify_branch(preview_key)


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
    # A supplied revision is what makes a preview frozen: the caller pinned
    # the commit rather than letting a moving branch resolve one.
    slug = preview_slug(preview_key, frozen=bool(revision))
    if not revision and is_reserved_preview_slug(slug):
        # Reachable: a branch may be named for a run, or for a preview
        # published under the earlier naming that is still on the host.
        raise EphemeralDeployError(
            f"[ephemeral] preview '{preview_key}' resolves to slug '{slug}', "
            "which is reserved for frozen release previews of a pinned "
            "candidate; rename the branch to deploy it as a branch preview"
        )
    return preview_key, slug


def require_unclaimed_by_another_candidate(
    project: str, preview_key: str, revision: str, *, read_recorded
) -> None:
    """Refuse a frozen occupancy already recorded against another candidate.

    A frozen preview's URL is cited as evidence that a specific commit is
    what a reviewer saw. Redeploying the same occupancy on a different
    commit makes every earlier citation of that URL wrong, so the recorded
    preview — not the caller's say-so — decides whether this claim stands.

    Redeploying the *same* candidate is the ordinary retry and is allowed;
    that is what makes a lost dispatch safe to repeat.
    """
    recorded, unreadable = read_recorded(project, preview_key)
    if unreadable:
        raise EphemeralDeployError(
            f"[ephemeral] whether preview '{preview_key}' is already serving "
            f"another candidate could not be determined: {unreadable}. That is "
            "unverified rather than unclaimed, and claiming it anyway could "
            "replace a candidate under review"
        )
    if recorded and recorded.lower() != revision.lower():
        raise EphemeralDeployError(
            f"[ephemeral] preview '{preview_key}' is recorded as serving "
            f"{recorded}, not {revision}; a frozen preview's URL is cited as "
            "evidence of the commit a reviewer saw, so it is not redeployed "
            "onto a different candidate"
        )


def require_unreserved_teardown(preview_key: str, slug: str, *, owned: bool) -> None:
    """Refuse a branch-named teardown of a frozen occupancy.

    The trespass read backwards: a caller naming an occupancy it never
    created would delete the preview a release is still being reviewed
    against. *owned* is the caller saying it is that release — which only
    reaches the reserved namespace at all through the frozen derivation.
    """
    if owned or not is_reserved_preview_slug(slug):
        return
    raise EphemeralDeployError(
        f"[ephemeral] preview '{preview_key}' resolves to slug '{slug}', "
        "which is reserved for frozen release previews; tear one down as "
        "the release preview it is, not by branch"
    )


__all__ = [
    "RETAINED_PREVIEW_SLUG_RE",
    "is_reserved_preview_slug",
    "preview_slug",
    "require_unclaimed_by_another_candidate",
    "require_unreserved_teardown",
    "resolve_deploy_occupancy",
]
