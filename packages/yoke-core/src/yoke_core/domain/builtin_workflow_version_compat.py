"""Serialization compatibility for published built-in workflow rows.

Existing universes hold definition rows written across vocabulary eras
and serialization styles. Convergence compares through these helpers and
rewrites semantically-equal rows to the code-owned canonical form.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)
from yoke_core.domain.workflow_registry_sql import marker

_BINDING_KEY = "skill_bindings"
_RETIRED_BINDING_KEY = "executor_bindings"
_RETIRED_BINDING_ID_KEY = "executor_id"


def _normalized_binding_vocabulary(definition: Mapping[str, Any]) -> dict:
    """Rename the retired binding vocabulary to the canonical one.

    Published rows predate the binding vocabulary cutover in mixed eras:
    some carry ``executor_bindings`` entries keyed by ``executor_id``,
    newer ones already carry ``skill_bindings`` keyed by ``skill_id``.
    The semantics are identical, so convergence compares (and rewrites)
    through this normalization instead of failing byte-equality against
    history no operator can edit.
    """
    if _RETIRED_BINDING_KEY not in definition:
        return dict(definition)
    normalized = dict(definition)
    bindings = normalized.pop(_RETIRED_BINDING_KEY)
    normalized[_BINDING_KEY] = [
        {
            ("skill_id" if key == _RETIRED_BINDING_ID_KEY else key): value
            for key, value in binding.items()
        }
        for binding in bindings
    ]
    return normalized


def _comparable_form(definition: Mapping[str, Any]) -> dict:
    """Definition reduced to what convergence treats as load-bearing.

    Binding vocabulary is normalized, and per-stage ``description``
    display copy is dropped: prose edits in the code-owned fixtures are
    adopted by the canonical rewrite rather than failing every existing
    universe's boot.
    """
    comparable = _normalized_binding_vocabulary(definition)
    stages = comparable.get("stages")
    if isinstance(stages, list):
        comparable["stages"] = [
            {k: v for k, v in stage.items() if k != "description"}
            if isinstance(stage, dict)
            else stage
            for stage in stages
        ]
    return comparable


def _rewrite_version_to_canonical(
    conn: Any,
    existing: Mapping[str, Any],
    definition: Mapping[str, Any],
) -> dict:
    """Rewrite a stored row to the code-owned canonical serialization.

    Reached only when the stored definition equals the code-owned one
    after retired-vocabulary normalization, so the rewrite can never
    change semantics — it re-serializes the same definition. The
    immutability trigger guards operators and product paths; convergence
    owns the trigger and suspends it for exactly this statement.
    """
    from yoke_core.domain.workflow_schema import (
        WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER,
    )

    bind = marker(conn)
    is_postgres = db_backend.connection_is_postgres(conn)
    if is_postgres:
        conn.execute(
            "ALTER TABLE workflow_versions DISABLE TRIGGER "
            f"{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}"
        )
    else:
        conn.execute(
            f"DROP TRIGGER IF EXISTS {WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}_update"
        )
    try:
        conn.execute(
            "UPDATE workflow_versions "
            f"SET definition_json = {bind}, definition_digest = {bind} "
            f"WHERE id = {bind}",
            (
                canonical_definition_json(definition),
                definition_digest(definition),
                existing["id"],
            ),
        )
    finally:
        if is_postgres:
            conn.execute(
                "ALTER TABLE workflow_versions ENABLE TRIGGER "
                f"{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}"
            )
        else:
            from yoke_core.domain.workflow_schema import (
                ensure_workflow_schema,
            )

            ensure_workflow_schema(conn)
    refreshed = dict(existing)
    refreshed["definition_json"] = canonical_definition_json(definition)
    refreshed["definition_digest"] = definition_digest(definition)
    return refreshed
