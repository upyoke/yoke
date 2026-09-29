"""Where QA evidence has to live for the people who review it.

A capture is reviewable only when the build serving its universe can open
it, because that build answers every reviewer's ``qa.artifact.read``.
Evidence writes from a ``*-db-admin`` database door relay to that build
(:mod:`yoke_contracts.qa_evidence_plane`); here a local write from such a
door refuses, and a review request refuses to exist while any artifact it
would show is unreadable where the reviewer looks.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from yoke_contracts.qa_evidence_plane import (
    administered_elsewhere_env,
    serving_env_label,
)

EVIDENCE_NOT_PORTABLE = "evidence_not_portable"


class EvidenceNotPortable(ValueError):
    """Evidence a reviewer would be shown cannot be opened where they look."""

    code = EVIDENCE_NOT_PORTABLE

    def __init__(self, message: str, recovery: str) -> None:
        super().__init__(f"{message} Recovery: {recovery}")
        self.recovery = recovery


def local_store_refusal(project: str) -> Optional[str]:
    """Why a local evidence write must not happen here, or None when it may."""
    admin = administered_elsewhere_env()
    if not admin:
        return None
    return (
        f"project {project!r} evidence would be written to this machine's disk "
        f"through database door {admin!r}, where no hosted reviewer can open "
        "it. Run the capture through the https connection that serves the "
        f"universe (`--env {serving_env_label(admin)}`), which "
        "stores evidence in the hosted artifact store."
    )


def _handle(artifact: dict[str, Any]) -> dict[str, Any]:
    from yoke_core.domain.qa_artifact_handle import (
        ArtifactHandleError,
        parse_handle,
    )

    try:
        return parse_handle(artifact.get("artifact_handle"))
    except ArtifactHandleError:
        return {}


def _hosted_serving_build() -> bool:
    """Whether this process is a hosted tenant build, whose store is remote."""
    from yoke_core.domain.qa_artifact_broker import (
        ArtifactBrokerError,
        broker_config,
    )

    try:
        return broker_config() is not None
    except ArtifactBrokerError:
        return True  # published but incomplete: still a hosted tenant


def unservable_artifacts(artifacts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Artifacts a hosted reviewer could not open.

    Object-store handles are servable by construction: they are recorded only
    after the serving plane minted and received the upload. A local handle
    names one machine's disk, which is the serving build's own disk only in
    a local or self-hosted universe. Behind a hosted build — or seen through
    a database door into one — it is a placeholder.
    """
    artifacts = list(artifacts)
    if not any(_handle(a).get("backend") == "local" for a in artifacts):
        return []
    if not (administered_elsewhere_env() or _hosted_serving_build()):
        return []
    return [a for a in artifacts if _handle(a).get("backend") != "s3"]


def rehome_command(requirement_id: int, artifact_ids: Iterable[int]) -> str:
    """The recovery that moves recorded local bytes into the hosted store."""
    flags = " ".join(f"--artifact-id {int(a)}" for a in artifact_ids)
    return f"yoke qa artifact rehome --requirement-id {int(requirement_id)} {flags}"


def require_servable_review_evidence(
    requirement_id: int, artifacts: Iterable[dict[str, Any]]
) -> None:
    """Refuse a review request that would show a reviewer a placeholder.

    A covered case's artifact keeps its own ``requirement_id``; the read and
    the recovery are both authorized against that owner, not the acceptance.
    """
    unservable = unservable_artifacts(artifacts)
    if not unservable:
        return
    owners: dict[int, list[int]] = {}
    for artifact in unservable:
        owner = int(artifact.get("requirement_id") or requirement_id)
        owners.setdefault(owner, []).append(int(artifact["artifact_id"]))
    ids = ", ".join(f"#{a}" for group in owners.values() for a in group)
    commands = "; ".join(
        rehome_command(owner, group) for owner, group in sorted(owners.items())
    )
    raise EvidenceNotPortable(
        f"requirement #{int(requirement_id)} cannot request human review: "
        f"artifact(s) {ids} are not readable by the build that serves this "
        "universe, so a hosted reviewer would see a placeholder instead of "
        "the evidence.",
        f"on the machine that captured them run `{commands}` to move the "
        "recorded bytes into the hosted store in place, then re-evaluate; "
        "if the bytes are gone, re-run the capture through the https "
        "connection that serves this universe.",
    )


__all__ = [
    "EVIDENCE_NOT_PORTABLE",
    "EvidenceNotPortable",
    "local_store_refusal",
    "rehome_command",
    "require_servable_review_evidence",
    "unservable_artifacts",
]
