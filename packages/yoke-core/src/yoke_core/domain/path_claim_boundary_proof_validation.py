"""Authoritative validation for caller-produced path-boundary proofs."""

from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import quote

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.gate_satisfier_ladder_catalog import (
    PATH_CLAIM_BOUNDARY_LADDER,
)
from yoke_core.domain.path_claims_boundary import BoundaryCheckStatus


PROOF_KIND = "path_claim_boundary_local_v1"
PROOF_FACT = "boundary_proof"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_CHECK_FIELDS = frozenset(
    {
        "status",
        "claim_id",
        "integration_target",
        "declared_target_ids",
        "declared_paths",
        "touched_paths",
        "uncommitted_paths",
        "undeclared_paths",
        "undeclared_target_ids",
        "declared_but_untouched_paths",
        "rename_pairs",
        "diagnostics",
    }
)
_CLEAR_STATUSES = frozenset(
    {
        BoundaryCheckStatus.VALID.value,
        BoundaryCheckStatus.DRIFTED.value,
        BoundaryCheckStatus.RENAME_RESOLVED.value,
    }
)


class BoundaryProofError(RuntimeError):
    """The proof is missing, stale, incomplete, or not locally producible."""


def validate_proof(
    conn: Any,
    *,
    context: dict,
    proof: dict,
    session_id: str,
    verify_remote: bool,
) -> dict:
    """Bind proof observations to current server-authoritative item facts."""
    if not isinstance(proof, dict) or proof.get("kind") != PROOF_KIND:
        raise BoundaryProofError("boundary proof kind is missing or unsupported")
    if type(proof.get("item_id")) is not int or proof["item_id"] != context["item_id"]:
        raise BoundaryProofError("boundary proof targets a different item")
    for key in ("lane", "work_claim", "claims"):
        if proof.get(key) != context.get(key):
            raise BoundaryProofError(f"boundary proof {key} facts are stale")
    holder = context.get("work_claim") or {}
    if not session_id or holder.get("session_id") != session_id:
        raise BoundaryProofError(
            "the active item work claim belongs to another session"
        )
    lane = context.get("lane") or {}
    if not _is_sha(str(lane.get("commit_sha") or "")):
        raise BoundaryProofError("the active lane has no current recorded revision")
    targets = sorted(
        {
            str(claim.get("integration_target") or "")
            for claim in context.get("claims") or []
        }
    )
    if not targets:
        raise BoundaryProofError("boundary proof has no path claims to check")
    declared_paths = sorted(
        {
            path
            for claim in context.get("claims") or []
            for path in claim.get("declared_paths") or []
        }
    )
    checks = proof.get("checks")
    if not isinstance(checks, list) or any(
        not isinstance(check, dict) for check in checks
    ):
        raise BoundaryProofError("boundary proof checks must be complete objects")
    if (
        sorted(str(check.get("integration_target") or "") for check in checks)
        != targets
    ):
        raise BoundaryProofError(
            "boundary proof does not check every integration target"
        )
    for check in checks:
        if not _CHECK_FIELDS.issubset(check):
            raise BoundaryProofError(
                "boundary proof contains an incomplete check result"
            )
        if check.get("status") not in _CLEAR_STATUSES or check.get("claim_id") != -1:
            raise BoundaryProofError("boundary proof contains an invalid check verdict")
        list_fields = _CHECK_FIELDS - {
            "status",
            "claim_id",
            "integration_target",
            "diagnostics",
        }
        if any(not isinstance(check.get(field), list) for field in list_fields):
            raise BoundaryProofError(
                "boundary proof check result has malformed path facts"
            )
        if sorted(check["declared_paths"]) != declared_paths:
            raise BoundaryProofError(
                "boundary proof check coverage is stale or incomplete"
            )
        if not isinstance(check.get("diagnostics"), str):
            raise BoundaryProofError("boundary proof check diagnostics are malformed")
        if check.get("uncommitted_paths") or check.get("undeclared_paths"):
            raise BoundaryProofError("boundary proof reports unresolved path drift")
    bases = proof.get("integration_bases")
    if not isinstance(bases, list) or any(not isinstance(base, dict) for base in bases):
        raise BoundaryProofError("boundary proof integration-base facts are malformed")
    if sorted(str(base.get("integration_target") or "") for base in bases) != targets:
        raise BoundaryProofError("boundary proof has incomplete integration-base facts")
    for base in bases:
        if not _is_sha(str(base.get("integration_base_sha") or "")) or not _is_sha(
            str(base.get("merge_base_sha") or "")
        ):
            raise BoundaryProofError(
                "boundary proof has an invalid integration-base SHA"
            )
    rung_id = str(proof.get("rung_id") or "")
    try:
        PATH_CLAIM_BOUNDARY_LADDER.rung(rung_id)
    except KeyError as exc:
        raise BoundaryProofError("boundary proof names an unsupported rung") from exc
    if verify_remote and rung_id == "remote_integration_ref":
        expected = _remote_heads(
            conn,
            str(context["project"]["slug"]),
            targets,
        )
        observed = {
            str(base["integration_target"]): str(base["integration_base_sha"])
            for base in bases
        }
        if expected is not None and observed != expected:
            raise BoundaryProofError(
                "the recorded remote integration base is stale; fetch the lane "
                "and produce a new boundary proof"
            )
        proof["integration_base_validation"] = (
            "github_api" if expected is not None else "caller_observed_remote_ref"
        )
    elif rung_id == "local_integration_ref":
        proof["integration_base_validation"] = "caller_observed_local_ref"
    return proof


def _remote_heads(
    conn: Any,
    project: str,
    targets: Iterable[str],
) -> dict[str, str] | None:
    from yoke_core.domain.github_actions_rest import rest_get
    from yoke_core.domain.project_github_auth import (
        MissingCapability,
        ProjectGithubAuthError,
        resolve_project_github_auth,
    )

    try:
        auth = resolve_project_github_auth(
            project,
            conn=conn,
            required_permissions=GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
        )
    except MissingCapability:
        return None
    except ProjectGithubAuthError as exc:
        raise BoundaryProofError(
            f"remote integration base is unreadable: {exc.code}: {exc}"
        ) from exc

    try:
        heads: dict[str, str] = {}
        for target in targets:
            data = rest_get(
                f"/repos/{auth.repo}/commits/{quote(target, safe='')}",
                token=auth.token,
            )
            sha = str((data or {}).get("sha") or "")
            if not _is_sha(sha):
                raise BoundaryProofError(
                    f"GitHub returned no commit SHA for {target!r}"
                )
            heads[target] = sha
        return heads
    except BoundaryProofError:
        raise
    except Exception as exc:
        raise BoundaryProofError(
            f"remote integration base is unreadable: {type(exc).__name__}: {exc}"
        ) from exc


def _is_sha(value: str) -> bool:
    return bool(_SHA.fullmatch(value))


__all__ = [
    "BoundaryProofError",
    "PROOF_FACT",
    "PROOF_KIND",
    "validate_proof",
]
