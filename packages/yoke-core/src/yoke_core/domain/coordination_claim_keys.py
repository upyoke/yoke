"""The operator-facing key string for one shared-operation claim.

Shared-operation claims are addressed by a single string —
``LIVE_DB_MIGRATION:<model>``, ``QA_HOST:<machine>`` — in operator
commands, contention messages, and doctor output, because a human
recovering a stranded resource types one token, not a JSON object.
Storage is the typed target; this module is the only place the two
representations are converted, so a key never means two things.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.coordination_claim_keys import (
    COORDINATION_KEY_PREFIXES as _PREFIXES,
    COORDINATION_TARGET_KINDS,
    DEPLOY_KEY_PREFIX,
    MIGRATION_KEY_PREFIX,
    QA_HOST_KEY_PREFIX,
    QUALIFICATION_KEY_PREFIX,
)
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_DEPLOY_SERIALIZATION,
    TARGET_KIND_MIGRATION_SERIALIZATION,
    TARGET_KIND_QA_ADMISSION,
    TARGET_KIND_ROUTE_QUALIFICATION,
    WorkClaimTarget,
    make_deploy_serialization_target,
    make_migration_serialization_target,
    make_qa_admission_target,
    make_route_qualification_target,
)


class CoordinationKeyError(ValueError):
    """Raised when a key names no registered shared-operation resource."""


def kind_for_key(key: str) -> Optional[str]:
    """Return the target kind a key addresses, or None when unregistered."""
    text = str(key or "")
    for prefix, kind in _PREFIXES:
        if text.startswith(prefix):
            return kind
    return None


def target_for_key(
    key: str,
    *,
    project_id: int,
    item_id: Optional[int] = None,
    project_slug: Optional[str] = None,
) -> WorkClaimTarget:
    """Resolve one operator key to its typed target.

    ``project_id`` scopes the kinds that are per-project. ``item_id`` is
    required only for migration territory, whose scope records the item
    that owns the hold; a lookup that does not know the owner passes the
    placeholder and matches on the exclusivity unit instead.

    A ``DEPLOY:`` key names the project twice — once as the caller's
    ``project_id`` and once as the slug in the key — so a mismatch is
    refused here rather than silently locking whichever one the caller
    happened to resolve.
    """
    kind = kind_for_key(key)
    if kind == TARGET_KIND_ROUTE_QUALIFICATION:
        return make_route_qualification_target(
            project_id, str(key)[len(QUALIFICATION_KEY_PREFIX):]
        )
    if kind == TARGET_KIND_MIGRATION_SERIALIZATION:
        return make_migration_serialization_target(
            project_id,
            str(key)[len(MIGRATION_KEY_PREFIX):],
            item_id if item_id is not None else 1,
        )
    if kind == TARGET_KIND_QA_ADMISSION:
        return make_qa_admission_target(str(key)[len(QA_HOST_KEY_PREFIX):])
    if kind == TARGET_KIND_DEPLOY_SERIALIZATION:
        slug = str(key)[len(DEPLOY_KEY_PREFIX):]
        if project_slug is not None and slug != project_slug:
            raise CoordinationKeyError(
                f"{key!r} names project {slug!r} but the call resolved "
                f"project {project_slug!r} (id {project_id}). Pass "
                f"--key {DEPLOY_KEY_PREFIX}{project_slug} to lock that "
                "project, or name the other project with --project."
            )
        return make_deploy_serialization_target(project_id, slug)
    raise CoordinationKeyError(
        f"{key!r} names no shared-operation resource; expected one of "
        + ", ".join(f"{prefix}…" for prefix, _ in _PREFIXES)
    )


def key_for_target(target: WorkClaimTarget) -> str:
    """Render the operator key addressing this target."""
    if target.kind == TARGET_KIND_MIGRATION_SERIALIZATION:
        return f"{MIGRATION_KEY_PREFIX}{target.model}"
    if target.kind == TARGET_KIND_QA_ADMISSION:
        return f"{QA_HOST_KEY_PREFIX}{target.machine_id}"
    if target.kind == TARGET_KIND_ROUTE_QUALIFICATION:
        return f"{QUALIFICATION_KEY_PREFIX}{target.grant_key}"
    if target.kind == TARGET_KIND_DEPLOY_SERIALIZATION:
        return f"{DEPLOY_KEY_PREFIX}{target.project_slug}"
    raise CoordinationKeyError(
        f"{target.kind!r} is not a shared-operation claim kind"
    )


def key_for_row(row: Any) -> str:
    """Render the operator key for one ``work_claims`` row."""
    from yoke_core.domain.work_claim_targets import from_row

    return key_for_target(from_row(row))


__all__ = [
    "COORDINATION_TARGET_KINDS",
    "CoordinationKeyError",
    "DEPLOY_KEY_PREFIX",
    "MIGRATION_KEY_PREFIX",
    "QA_HOST_KEY_PREFIX",
    "QUALIFICATION_KEY_PREFIX",
    "key_for_row",
    "key_for_target",
    "kind_for_key",
    "target_for_key",
]
