"""Atomically enter declared migration territory while widening a path claim."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain import db_compatibility_attestation as dca
from yoke_core.domain import db_mutation_profile as dmp
from yoke_core.domain.db_claim_apply import (
    AmendmentResult,
    _missing_required_authored_fields,
)
from yoke_core.domain.migration_model_capability import (
    CAPABILITY_TYPE,
    MigrationModelCapabilityError,
    validate as validate_capability,
)
from yoke_core.domain.path_claims import ClaimNotFound, PathClaimError
from yoke_core.domain.path_project_relative import invalid_project_relative_paths
from yoke_core.domain.workflow_item_binding_lock import lock_path_claim_workflow_binding


class MigrationPathClaimError(PathClaimError):
    """The requested widen cannot satisfy the migration-authoring contract."""


@dataclass(frozen=True)
class WidenedPathClaim:
    amendment_id: int
    migration_model: str | None = None
    migration_lease_id: int | None = None
    db_claim_event_id: str | None = None


@dataclass(frozen=True)
class MigrationPathClaimContext:
    item_id: int
    project_id: int
    project: str
    profile_raw: Any
    attestation_raw: Any


@dataclass(frozen=True)
class _MigrationScope:
    model_name: str
    modules_dir: str
    module_identifiers: tuple[str, ...]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _parse_object(raw: Any, *, field: str) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str) or not raw:
        raise MigrationPathClaimError(f"{field} is missing or malformed")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MigrationPathClaimError(f"{field} is malformed: {exc}") from exc
    if not isinstance(parsed, dict):
        raise MigrationPathClaimError(f"{field} must be a JSON object")
    return parsed


def lock_claim_for_widen(
    conn: Any, *, claim_id: int, expected_item_id: int | None
) -> MigrationPathClaimContext:
    lock_path_claim_workflow_binding(conn, claim_id)
    suffix = " FOR UPDATE OF pc" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        "SELECT pc.owner_kind, pc.owner_item_id, i.project_id, p.slug, "
        "i.db_mutation_profile, i.db_compatibility_attestation "
        "FROM path_claims pc "
        "LEFT JOIN items i ON pc.owner_kind = 'item' AND i.id = pc.owner_item_id "
        "LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE pc.id = {_p(conn)}{suffix}",
        (claim_id,),
    ).fetchone()
    if row is None:
        raise ClaimNotFound(f"path_claims id {claim_id} does not exist")
    if row[0] != "item" or row[1] is None or row[2] is None or row[3] is None:
        raise MigrationPathClaimError(f"claim {claim_id} has no item/project owner")
    item_id = int(row[1])
    if expected_item_id is not None and item_id != int(expected_item_id):
        raise MigrationPathClaimError(
            f"claim {claim_id} belongs to item {item_id}, not target item "
            f"{int(expected_item_id)}"
        )
    return MigrationPathClaimContext(
        item_id=item_id,
        project_id=int(row[2]),
        project=str(row[3]),
        profile_raw=row[4],
        attestation_raw=row[5],
    )


def _new_target_paths(
    conn: Any,
    *,
    claim_id: int,
    project_id: int,
    target_ids: Sequence[int],
) -> list[str]:
    existing = {
        int(row[0])
        for row in conn.execute(
            f"SELECT target_id FROM path_claim_targets WHERE claim_id = {_p(conn)}",
            (claim_id,),
        )
    }
    new_ids = [int(target_id) for target_id in target_ids if target_id not in existing]
    if not new_ids:
        return []
    placeholders = ", ".join(_p(conn) for _ in new_ids)
    rows = conn.execute(
        f"SELECT id, project_id, path_string FROM path_targets "
        f"WHERE id IN ({placeholders})",
        tuple(new_ids),
    ).fetchall()
    by_id = {int(row[0]): (int(row[1]), str(row[2])) for row in rows}
    missing = [target_id for target_id in new_ids if target_id not in by_id]
    if missing:
        raise MigrationPathClaimError(f"path_targets row(s) {missing!r} do not exist")
    foreign = [
        by_id[target_id][1]
        for target_id in new_ids
        if by_id[target_id][0] != project_id
    ]
    if foreign:
        raise MigrationPathClaimError(
            "path claim widening cannot cross projects: " + ", ".join(foreign)
        )
    return [by_id[target_id][1] for target_id in new_ids]


def _capability_settings(conn: Any, context: MigrationPathClaimContext) -> dict | None:
    row = conn.execute(
        "SELECT settings FROM project_capabilities "
        f"WHERE project_id = {_p(conn)} AND type = {_p(conn)}",
        (context.project_id, CAPABILITY_TYPE),
    ).fetchone()
    if row is None:
        return None
    try:
        return validate_capability(
            _parse_object(row[0], field="migration_model capability settings")
        )
    except MigrationModelCapabilityError as exc:
        raise MigrationPathClaimError(
            f"project '{context.project}' migration_model capability is invalid: {exc}"
        ) from exc


def _normalized_dir(raw: str) -> str:
    normalized = raw.strip().rstrip("/")
    if (
        not normalized
        or normalized == "."
        or invalid_project_relative_paths([normalized])
    ):
        raise MigrationPathClaimError(f"invalid runner.config.modules_dir: {raw!r}")
    return normalized


def _scope_for_paths(settings: Mapping[str, Any] | None, paths: Sequence[str]):
    if settings is None or not paths:
        return None
    matches: dict[str, tuple[str, list[str]]] = {}
    for model_name, model in (settings.get("models") or {}).items():
        config = (model.get("runner") or {}).get("config") or {}
        modules_dir = _normalized_dir(str(config.get("modules_dir") or ""))
        prefix = f"{modules_dir}/"
        matched = [
            path
            for path in paths
            if path.rstrip("/") == modules_dir or path.startswith(prefix)
        ]
        if matched:
            matches[str(model_name)] = (modules_dir, matched)
    if len(matches) > 1:
        raise MigrationPathClaimError(
            "one path widen cannot enter multiple migration models: "
            + ", ".join(sorted(matches))
        )
    if not matches:
        return None
    model_name, (modules_dir, matched_paths) = next(iter(matches.items()))
    identifiers: list[str] = []
    for path in matched_paths:
        relative = path.removeprefix(f"{modules_dir}/")
        if "/" not in relative and relative.endswith(".py"):
            name = relative.removesuffix(".py")
            if name != "__init__":
                identifiers.append(name)
    return _MigrationScope(
        model_name=model_name,
        modules_dir=modules_dir,
        module_identifiers=tuple(dict.fromkeys(identifiers)),
    )


def _validate_matching_claim(
    *, profile_raw: Any, attestation_raw: Any, scope: _MigrationScope
) -> None:
    try:
        profile = dmp.validate(_parse_object(profile_raw, field="db_mutation_profile"))
    except (dmp.DbMutationProfileError, MigrationPathClaimError) as exc:
        raise MigrationPathClaimError(f"db_mutation_profile is invalid: {exc}") from exc
    if profile.get("state") != dmp.STATE_DECLARED:
        raise MigrationPathClaimError(
            "migration path widening requires db_mutation_profile.state='declared' "
            "or a full db_claim amendment payload"
        )
    if profile.get("model_name") != scope.model_name:
        raise MigrationPathClaimError(
            f"db_mutation_profile.model_name must be '{scope.model_name}' for "
            f"runner.config.modules_dir '{scope.modules_dir}'"
        )
    declared_modules = set(profile.get("migration_modules") or [])
    missing_modules = sorted(set(scope.module_identifiers) - declared_modules)
    if missing_modules:
        raise MigrationPathClaimError(
            "db_mutation_profile.migration_modules does not declare widened "
            f"module(s): {missing_modules}"
        )
    try:
        attestation = dca.validate(
            _parse_object(attestation_raw, field="db_compatibility_attestation")
        )
    except (dca.DbCompatibilityAttestationError, MigrationPathClaimError) as exc:
        raise MigrationPathClaimError(
            f"db_compatibility_attestation is invalid: {exc}"
        ) from exc
    if not attestation.get(dca.FREEZE_FIELD):
        raise MigrationPathClaimError(
            "db_compatibility_attestation must carry a valid frozen_at stamp"
        )
    if profile.get("compatibility_class") == dmp.COMPATIBILITY_PRE_MERGE_SAFE:
        missing = _missing_required_authored_fields(attestation)
        if missing:
            raise MigrationPathClaimError(
                "pre_merge_safe migration claim has missing/empty attestation "
                f"fields: {missing}"
            )


def widen_locked_claim(
    conn: Any,
    *,
    claim_id: int,
    context: MigrationPathClaimContext,
    add_target_ids: Sequence[int],
    reason: str,
    session_id: str,
    db_claim_payload: Mapping[str, Any] | None = None,
    repo_path: str | None = None,
    worktree_head: str | None = None,
) -> WidenedPathClaim:
    """Widen one claim, acquiring declared migration territory when needed."""
    try:
        target_ids = list(dict.fromkeys(int(value) for value in add_target_ids))
        new_paths = _new_target_paths(
            conn,
            claim_id=claim_id,
            project_id=context.project_id,
            target_ids=target_ids,
        )
        scope = _scope_for_paths(_capability_settings(conn, context), new_paths)
        claim_amendment: AmendmentResult | None = None
        lease_id: int | None = None
        if scope is None:
            if db_claim_payload is not None:
                raise MigrationPathClaimError(
                    "db_claim payload is only accepted when new coverage enters "
                    "a declared runner.config.modules_dir"
                )
        else:
            profile_raw = context.profile_raw
            attestation_raw = context.attestation_raw
            if db_claim_payload is not None:
                from yoke_core.domain.db_claim import amend

                claim_amendment = amend(
                    context.item_id,
                    db_claim_payload,
                    reason=reason,
                    conn=conn,
                    session_id=session_id,
                    commit=False,
                )
                profile_raw = claim_amendment.new_profile
                attestation_raw = claim_amendment.new_attestation
            _validate_matching_claim(
                profile_raw=profile_raw, attestation_raw=attestation_raw, scope=scope
            )
            from yoke_core.domain import migration_territory_lease

            lease = migration_territory_lease.enter(
                conn,
                project=context.project_id,
                model_name=scope.model_name,
                session_id=session_id,
                commit=False,
            )
            lease_id = lease.id

        from yoke_core.domain.path_claims_amend import widen

        amendment_id = widen(
            conn,
            claim_id=claim_id,
            add_target_ids=target_ids,
            reason=reason,
            repo_path=repo_path,
            worktree_head=worktree_head,
            commit=False,
        )
        conn.commit()
        return WidenedPathClaim(
            amendment_id=amendment_id,
            migration_model=scope.model_name if scope else None,
            migration_lease_id=lease_id,
            db_claim_event_id=claim_amendment.event_id if claim_amendment else None,
        )
    except Exception:
        conn.rollback()
        raise


__all__ = [
    "MigrationPathClaimContext",
    "MigrationPathClaimError",
    "WidenedPathClaim",
    "lock_claim_for_widen",
    "widen_locked_claim",
]
