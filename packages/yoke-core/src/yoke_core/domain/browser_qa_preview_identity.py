"""Where a project's preview publishes its commit, and whether it matches.

A preview deployment can answer for itself. What this module owns is *which*
deployment is allowed to answer: the origin is derived from the project's
own ephemeral-env capability and the branch under test, never from a URL the
caller passed in. A target someone names on the command line proves nothing
about this project's preview — it could be any host serving any commit — so
the answer is only ever sought where the project's own configuration says
that preview lives.

The reading itself belongs to :mod:`served_revision_probe`, which registered
environments use the same way from their own settings.
"""

from __future__ import annotations

from dataclasses import dataclass

from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.browser_qa_freshness_outcome import (
    FreshnessFailure,
    IDENTITY_PROOF_MALFORMED,
    IDENTITY_PROOF_UNAVAILABLE,
    SHA_MISMATCH,
)


@dataclass(frozen=True)
class PreviewIdentityTarget:
    """Where this project's preview for a branch publishes its commit.

    Exactly one of these is true, and keeping them apart is the point:
    ``origin``/``path`` are set when the project publishes such a proof;
    ``unconfigured`` when it genuinely publishes none; ``unreadable`` when
    the configuration could not be read at all. Reporting the third as the
    second would claim a project declined something it was never asked.
    """

    origin: str = ""
    path: str = ""
    unconfigured: bool = False
    unreadable: str = ""
    # How this project's previews are deployed. A release preview must be
    # deployed by something that can take the run's own key and frozen
    # revision, and not every trigger can, so the caller needs this to
    # refuse rather than deploy the wrong thing.
    trigger: str = ""


def resolve_preview_identity_target(
    project: str, preview_key: str
) -> PreviewIdentityTarget:
    """Derive the preview identity endpoint from the project's own policy.

    *preview_key* is whatever names this preview in the project's own
    scheme: a branch for a branch preview, a deployment run for a release
    preview. Both slugify through the same derivation the wildcard router
    and the deploy workflow use, so the origin this returns is the one the
    preview is actually published at.
    """
    import json

    from yoke_core.domain.control_plane_transport import relay
    from yoke_core.domain.ephemeral_substrate import (
        EphemeralPolicyError,
        ephemeral_policy_from_capability,
        preview_url,
        slugify_branch,
    )

    # Existence is asked first, and separately, because the settings read
    # answers a missing capability with the same failure shape as a denied
    # or unavailable one. "This project has no ephemeral-env capability" is
    # an answer; "we could not ask" is not, and collapsing them would report
    # every project without previews as an infrastructure problem.
    try:
        declared = relay(
            "projects.capability.has",
            {"project": project, "cap_type": "ephemeral-env"},
        ).get("has")
    except Exception as exc:
        return PreviewIdentityTarget(unreadable=f"capability read failed: {exc}")
    if not declared:
        return PreviewIdentityTarget(unconfigured=True)

    try:
        result = relay(
            "projects.capability_settings.get",
            {"project": project, "cap_type": "ephemeral-env"},
        )
    except Exception as exc:
        # The capability exists but its settings could not be read: denied,
        # unavailable, or erroring. That is not an answer about what the
        # project configured.
        return PreviewIdentityTarget(unreadable=f"capability read failed: {exc}")
    raw = result.get("settings_json")
    try:
        cap = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, ValueError) as exc:
        return PreviewIdentityTarget(unreadable=f"capability settings are not JSON: {exc}")
    if not isinstance(cap, dict) or not cap:
        return PreviewIdentityTarget(unconfigured=True)
    try:
        policy = ephemeral_policy_from_capability(project, cap)
    except EphemeralPolicyError as exc:
        return PreviewIdentityTarget(unreadable=str(exc))
    if not policy.identity_path:
        return PreviewIdentityTarget(unconfigured=True)
    return PreviewIdentityTarget(
        origin=preview_url(slugify_branch(preview_key), policy.preview_domain),
        path=policy.identity_path,
        trigger=policy.trigger,
    )


def verify_preview_identity(
    project: str,
    branch: str,
    expected_sha: str,
    *,
    target: PreviewIdentityTarget,
    fetch=None,
) -> FreshnessFailure | None:
    """Judge what this project's preview for *branch* says it is serving."""
    from yoke_core.domain import browser_qa as _bqa

    outcome = probe.probe_served_revision(
        target.origin, target.path, expected_sha=expected_sha, fetch=fetch
    )
    if outcome.kind == probe.UNREACHABLE:
        return FreshnessFailure(
            IDENTITY_PROOF_UNAVAILABLE,
            f"No deployment record exists for branch '{branch}' in project "
            f"'{project}', and its preview could not answer at {outcome.url}: "
            f"{outcome.detail}. Nothing here proves what is deployed, so this "
            "is unverified rather than stale; confirm the preview is up and "
            "serving that path.",
        )
    if outcome.kind == probe.MALFORMED:
        return FreshnessFailure(
            IDENTITY_PROOF_MALFORMED,
            f"The preview at {outcome.url} answered with {outcome.detail}, "
            "which is not a full 40-character commit SHA. An abbreviation or "
            "a page is not proof; serve the exact commit identity there.",
        )
    if outcome.kind == probe.MISMATCH:
        return FreshnessFailure(
            SHA_MISMATCH,
            f"The preview at {outcome.url} is serving {outcome.served}, not "
            f"the expected {expected_sha}. This is the commit it reported "
            "about itself, not a stored record; deploy the expected commit "
            "before running this case.",
        )
    _bqa._log(
        "Freshness check passed against the revision served at "
        f"{outcome.url}: branch={branch}, sha={expected_sha}"
    )
    return None


__all__ = [
    "PreviewIdentityTarget",
    "resolve_preview_identity_target",
    "verify_preview_identity",
]
