"""Where QA evidence has to live for the people who review it.

A capture is reviewable only when the build serving its universe can open
it, because that build answers every reviewer's ``qa.artifact.read``. A
process holding a ``*-db-admin`` connection is a database door into a
universe some other build serves: bytes it writes to its own disk are
readable on this machine and nowhere a reviewer looks. So evidence writes
from such a process go to the serving plane's store, a local write refuses,
and a review request refuses to exist while any artifact it would show
lives only on a capture machine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.machine_config.schema import (
    DB_ADMIN_ENV_SUFFIX,
    same_universe_https_env,
)
from yoke_contracts.schema_authority import serving_build_authority_declared

EVIDENCE_NOT_PORTABLE = "evidence_not_portable"
EVIDENCE_PLANE_UNRESOLVED = "evidence_plane_unresolved"

#: QA functions that write evidence bytes or the handle naming them. They run
#: where the universe's artifact store is configured, never on a database door.
EVIDENCE_WRITE_FUNCTIONS = frozenset(
    {"qa.artifact.add", "qa.artifact.presign", "qa.artifact.rehome"}
)


class EvidenceNotPortable(ValueError):
    """Evidence a reviewer would be shown cannot be opened where they look."""

    code = EVIDENCE_NOT_PORTABLE

    def __init__(self, message: str, recovery: str) -> None:
        super().__init__(f"{message} Recovery: {recovery}")
        self.recovery = recovery


class EvidencePlaneUnresolved(RuntimeError):
    """A database door names no https plane that could store its evidence."""

    code = EVIDENCE_PLANE_UNRESOLVED


def administered_elsewhere_env() -> str:
    """The ``*-db-admin`` label when another build serves this universe.

    Empty for a local universe, for an https connection (whose calls already
    execute on the serving build), and for a process that declared it serves
    the database it holds.
    """
    if serving_build_authority_declared():
        return ""
    try:
        env = str(machine_config_runtime.active_env() or "")
    except Exception:  # noqa: BLE001 - no readable selection is no admin door
        return ""
    return env if env.endswith(DB_ADMIN_ENV_SUFFIX) else ""


def evidence_relay_env() -> Optional[str]:
    """The https env that must run evidence writes for this process, or None."""
    admin = administered_elsewhere_env()
    if not admin:
        return None
    served = same_universe_https_env(machine_config_runtime.load_config(), admin)
    if not served:
        base = admin[: -len(DB_ADMIN_ENV_SUFFIX)]
        raise EvidencePlaneUnresolved(
            f"connection {admin!r} administers a universe served elsewhere, but "
            f"its https plane {base!r} is not configured here, so QA evidence "
            "has no store a reviewer can read. Configure it with `yoke "
            f"connection set {base} --api-url ...`, then re-run the capture."
        )
    return served


def local_store_refusal(project: str) -> Optional[str]:
    """Why a local evidence write must not happen here, or None when it may."""
    admin = administered_elsewhere_env()
    if not admin:
        return None
    return (
        f"project {project!r} evidence would be written to this machine's disk "
        f"through database door {admin!r}, where no hosted reviewer can open "
        "it. Run the capture through the https connection that serves the "
        f"universe (`--env {admin[: -len(DB_ADMIN_ENV_SUFFIX)]}`), which "
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


def unservable_artifacts(
    artifacts: Iterable[dict[str, Any]],
    *,
    project_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Artifacts the serving build could not hand a reviewer.

    Object-store handles are servable by construction: they are recorded only
    after the serving plane minted and received the upload. A local handle is
    servable only where this process is the serving build and the file is on
    its disk.
    """
    remote = bool(administered_elsewhere_env())
    unservable = []
    for artifact in artifacts:
        handle = _handle(artifact)
        if handle.get("backend") == "s3":
            continue
        if handle.get("backend") == "local" and not remote:
            path = Path(str(handle["path"])).expanduser()
            if not path.is_absolute():
                from yoke_core.domain.project_checkout_locations import (
                    checkout_for_project_id,
                )

                checkout = checkout_for_project_id(project_id)
                path = checkout / path if checkout is not None else path
            if path.is_file():
                continue
        unservable.append(artifact)
    return unservable


def rehome_command(requirement_id: int, artifact_ids: Iterable[int]) -> str:
    """The recovery that moves recorded local bytes into the hosted store."""
    flags = " ".join(f"--artifact-id {int(a)}" for a in artifact_ids)
    return f"yoke qa artifact rehome --requirement-id {int(requirement_id)} {flags}"


def require_servable_review_evidence(
    requirement_id: int,
    artifacts: Iterable[dict[str, Any]],
    *,
    project_id: Optional[int] = None,
) -> None:
    """Refuse a review request that would show a reviewer a placeholder.

    A covered case's artifact keeps its own ``requirement_id``; the read and
    the recovery are both authorized against that owner, not the acceptance.
    """
    unservable = unservable_artifacts(artifacts, project_id=project_id)
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
    "EVIDENCE_PLANE_UNRESOLVED",
    "EVIDENCE_WRITE_FUNCTIONS",
    "EvidenceNotPortable",
    "EvidencePlaneUnresolved",
    "administered_elsewhere_env",
    "evidence_relay_env",
    "local_store_refusal",
    "rehome_command",
    "require_servable_review_evidence",
    "unservable_artifacts",
]
