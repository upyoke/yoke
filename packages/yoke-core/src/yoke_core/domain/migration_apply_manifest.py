"""Committed-manifest subject for ticketless governed migrations.

The normal two-unit runner derives its safety theorem from an item profile.
Some operator-directed maintenance is deliberately itemless. This module
provides the equivalent immutable subject from a committed JSON manifest in a
clean worktree, while leaving rehearsal, fingerprinting, leases, backups,
verification, and audit rows owned by the existing runner.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_core.domain import json_helper
from yoke_core.domain.db_compatibility_attestation import AUTHORED_FIELDS, validate as validate_attestation
from yoke_core.domain.db_mutation_profile import (
    MUTATION_INTENT_APPLY,
    STATE_DECLARED,
    validate as validate_profile,
)
from yoke_core.domain.migration_apply_audit import DESCRIPTION_BASE
from yoke_core.domain.migration_apply_contract import MigrationApplyError
from yoke_core.domain.migration_apply_resolve import _load_item, _resolve_capability_settings
from yoke_core.domain.migration_apply_resolve import _resolve_profile_or_raise, _resolve_repo_path
from yoke_core.domain.migration_model_capability_defaults import resolve_model
from yoke_core.domain.project_identity import resolve_project_id


MANIFEST_VERSION = 1
_TOP_LEVEL_KEYS = frozenset({"version", "project", "profile", "attestation"})
_SOURCE_COMMIT_MARKER = "manifest_source_commit="


class MigrationManifestError(MigrationApplyError):
    """A ticketless migration manifest or its source checkout is unsafe."""


@dataclass(frozen=True)
class MigrationApplySubject:
    """Validated input theorem consumed by both governed-runner units."""

    item_id: Optional[int]
    project: str
    project_id: int
    profile: Mapping[str, Any]
    attestation: Mapping[str, Any]
    audit_description: str
    manifest_relative_path: Path


@dataclass(frozen=True)
class ResolvedMigrationInput:
    """Item or manifest values consumed by the shared runner core."""

    item_id: Optional[int]
    project: str
    project_id: int
    profile: Mapping[str, Any]
    attestation_raw: Any


def validate_manifest_payload(
    payload: Any,
) -> tuple[str, Mapping[str, Any], Mapping[str, Any]]:
    """Validate the DB-independent theorem carried by a manifest payload.

    Source-checkout execution adds project lookup, checkout authority, tracked
    file, and exact-commit checks.  Hosted engine fleets reuse this pure layer
    before applying the same packaged migration module to a tenant database;
    their fleet control plane is intentionally not the tenant target.
    """

    if not isinstance(payload, dict):
        raise MigrationManifestError("migration manifest root must be an object")
    unknown = set(payload) - _TOP_LEVEL_KEYS
    missing = _TOP_LEVEL_KEYS - set(payload)
    if unknown or missing:
        raise MigrationManifestError(
            f"migration manifest keys invalid; missing={sorted(missing)} "
            f"unknown={sorted(unknown)}"
        )
    if payload.get("version") != MANIFEST_VERSION:
        raise MigrationManifestError(
            f"migration manifest version must be {MANIFEST_VERSION}"
        )

    project = payload.get("project")
    if not isinstance(project, str) or not project.strip():
        raise MigrationManifestError("migration manifest project must be non-empty")
    project = project.strip()
    try:
        profile = validate_profile(payload.get("profile"))
        attestation = validate_attestation(payload.get("attestation"))
    except ValueError as exc:
        raise MigrationManifestError(f"migration manifest theorem invalid: {exc}") from exc
    if profile.get("state") != STATE_DECLARED:
        raise MigrationManifestError("migration manifest profile must be declared")
    if profile.get("mutation_intent") != MUTATION_INTENT_APPLY:
        raise MigrationManifestError("migration manifest profile intent must be apply")
    missing_attestations = sorted(
        field for field in AUTHORED_FIELDS if not attestation.get(field)
    )
    if missing_attestations:
        raise MigrationManifestError(
            "migration manifest attestation has empty authored fields: "
            + ", ".join(missing_attestations)
        )
    return project, profile, attestation


def resolve_runner_input(
    control_conn: Any,
    *,
    item_id: Optional[int],
    subject: Optional[MigrationApplySubject],
) -> ResolvedMigrationInput:
    """Normalize item-backed and manifest-backed inputs once."""

    if subject is not None:
        return ResolvedMigrationInput(
            item_id=None,
            project=subject.project,
            project_id=subject.project_id,
            profile=dict(subject.profile),
            attestation_raw=json_helper.dumps_compact(subject.attestation),
        )
    if item_id is None:
        raise MigrationManifestError("item-backed migration requires item_id")
    item = _load_item(control_conn, item_id)
    return ResolvedMigrationInput(
        item_id=item_id,
        project=str(item.get("project") or ""),
        project_id=int(item["project_id"]),
        profile=_resolve_profile_or_raise(item),
        attestation_raw=item.get("db_compatibility_attestation"),
    )


def resolve_manifest_subject(
    control_conn: Any,
    *,
    manifest_path: Path,
    worktree_path: Path,
) -> MigrationApplySubject:
    """Load and validate a committed manifest from a clean project worktree."""

    root = Path(worktree_path).expanduser().resolve()
    if not root.is_dir():
        raise MigrationManifestError(f"worktree path is not a directory: {root}")
    _require_clean_git_checkout(root)

    candidate = Path(manifest_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_symlink():
        raise MigrationManifestError("migration manifest must not be a symlink")
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise MigrationManifestError(
            f"migration manifest escapes worktree {root}: {resolved}"
        ) from exc
    if not resolved.is_file():
        raise MigrationManifestError(f"migration manifest is not a file: {resolved}")
    _require_tracked(root, relative)

    try:
        payload = json_helper.load_path(resolved)
    except (OSError, ValueError) as exc:
        raise MigrationManifestError(f"cannot parse migration manifest: {exc}") from exc
    project, profile, attestation = validate_manifest_payload(payload)
    try:
        project_id = resolve_project_id(control_conn, project)
    except LookupError as exc:
        raise MigrationManifestError(
            f"migration manifest project is unknown: {project!r}"
        ) from exc
    _require_registered_checkout(control_conn, root, project)

    capability = _resolve_capability_settings(control_conn, project)
    try:
        model = resolve_model(capability, str(profile["model_name"]))
    except KeyError as exc:
        raise MigrationManifestError(
            f"model {profile['model_name']!r} is not declared for {project!r}"
        ) from exc
    modules_dir = str(
        (model.get("runner") or {}).get("config", {}).get("modules_dir") or ""
    )
    if not modules_dir:
        raise MigrationManifestError("migration model has no modules_dir")
    for identifier in profile["migration_modules"]:
        module_path = Path(modules_dir) / f"{identifier}.py"
        candidate_module = root / module_path
        if candidate_module.is_symlink():
            raise MigrationManifestError(f"migration module must not be a symlink: {module_path}")
        resolved_module = candidate_module.resolve()
        try:
            resolved_module.relative_to(root)
        except ValueError as exc:
            raise MigrationManifestError(
                f"migration module escapes worktree: {module_path}"
            ) from exc
        if not resolved_module.is_file():
            raise MigrationManifestError(
                f"migration module is missing from source checkout: {module_path}"
            )
        _require_tracked(root, module_path)

    commit = _git_capture(root, ["rev-parse", "HEAD"])
    if len(commit) != 40:
        raise MigrationManifestError("migration worktree has no full source commit")
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    description = (
        f"{DESCRIPTION_BASE}; {_SOURCE_COMMIT_MARKER}{commit}; "
        f"manifest_path={relative.as_posix()}; manifest_sha256={digest}"
    )
    return MigrationApplySubject(
        item_id=None,
        project=project,
        project_id=project_id,
        profile=profile,
        attestation=attestation,
        audit_description=description,
        manifest_relative_path=relative,
    )


def assert_manifest_subject_current(
    control_conn: Any, *, subject: MigrationApplySubject, worktree_path: Path
) -> None:
    """Revalidate the exact clean source immediately before module loading."""

    current = resolve_manifest_subject(
        control_conn,
        manifest_path=subject.manifest_relative_path,
        worktree_path=worktree_path,
    )
    if current.audit_description != subject.audit_description:
        raise MigrationManifestError(
            "migration source commit or manifest changed after subject resolution"
        )


def assert_manifest_source_consistent(
    *,
    identifier: str,
    audit_description: Optional[str],
    subject: MigrationApplySubject,
) -> None:
    """Require live apply to use the exact manifest source rehearsed earlier."""

    if audit_description == subject.audit_description:
        return
    if not audit_description or _SOURCE_COMMIT_MARKER not in audit_description:
        detail = "rehearsed audit row has no itemless manifest source marker"
    else:
        detail = "live source commit or manifest digest differs from rehearsal"
    raise MigrationManifestError(f"module {identifier!r}: {detail}")


def assert_item_rehearsal_not_manifest(
    *, identifier: str, audit_description: Optional[str]
) -> None:
    """Prevent an item-backed live unit from consuming a manifest rehearsal."""

    if audit_description and _SOURCE_COMMIT_MARKER in audit_description:
        raise MigrationManifestError(
            f"module {identifier!r}: item-backed live apply cannot consume "
            "an itemless manifest rehearsal"
        )


def assert_rehearsal_subject_consistent(
    *,
    identifier: str,
    audit_description: Optional[str],
    subject: Optional[MigrationApplySubject],
) -> None:
    """Keep item and manifest rehearsals isolated at live promotion."""

    if subject is None:
        assert_item_rehearsal_not_manifest(
            identifier=identifier, audit_description=audit_description
        )
        return
    assert_manifest_source_consistent(
        identifier=identifier,
        audit_description=audit_description,
        subject=subject,
    )


def _require_clean_git_checkout(root: Path) -> None:
    if _git_capture(root, ["rev-parse", "--is-inside-work-tree"]) != "true":
        raise MigrationManifestError(f"not a git worktree: {root}")
    status = _git_capture(root, ["status", "--porcelain", "--untracked-files=all"])
    if status:
        raise MigrationManifestError("ticketless governed migration requires a clean source worktree")


def _require_registered_checkout(control_conn: Any, root: Path, project: str) -> None:
    registered = _resolve_repo_path(control_conn, project).resolve()
    if _git_common_dir(root) != _git_common_dir(registered):
        raise MigrationManifestError(
            f"worktree {root} is not attached to registered checkout {registered}"
        )


def _git_common_dir(root: Path) -> Path:
    raw = _git_capture(root, ["rev-parse", "--git-common-dir"])
    path = Path(raw)
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def _require_tracked(root: Path, relative: Path) -> None:
    result = _git_run(root, ["ls-files", "--error-unmatch", relative.as_posix()])
    if result.returncode != 0:
        raise MigrationManifestError(
            f"migration source is not tracked at HEAD: {relative.as_posix()}"
        )


def _git_capture(root: Path, argv: list[str]) -> str:
    result = _git_run(root, argv)
    if result.returncode != 0:
        raise MigrationManifestError(
            f"git {' '.join(argv)} failed in {root}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _git_run(root: Path, argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *argv],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise MigrationManifestError(f"git source validation failed: {exc}") from exc


__all__ = [
    "MANIFEST_VERSION",
    "MigrationApplySubject",
    "MigrationManifestError",
    "ResolvedMigrationInput",
    "assert_item_rehearsal_not_manifest",
    "assert_manifest_subject_current",
    "assert_manifest_source_consistent",
    "assert_rehearsal_subject_consistent",
    "resolve_manifest_subject",
    "resolve_runner_input",
    "validate_manifest_payload",
]
