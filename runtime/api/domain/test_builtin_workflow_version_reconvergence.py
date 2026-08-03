"""Converge heals published rows whose serialization drifted from code.

Existing universes hold built-in definition rows written in earlier
vocabularies or non-canonical serializations. Boot convergence must
rewrite semantically-equal rows to the canonical form instead of
refusing to boot, while still failing loudly on real definition drift.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.workflow_definition_codec import (
    WorkflowRegistryError,
    canonical_definition_json,
    definition_digest,
)
from yoke_core.domain.workflow_registry import converge_builtin_workflows
from yoke_core.domain.workflow_schema import (
    WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER,
)


def _overwrite_row(conn, workflow_id: str, version: int, payload: str,
                   digest: str) -> None:
    conn.execute(
        "ALTER TABLE workflow_versions DISABLE TRIGGER "
        f"{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}"
    )
    try:
        conn.execute(
            "UPDATE workflow_versions SET definition_json = %s, "
            "definition_digest = %s "
            "WHERE workflow_id = %s AND version = %s",
            (payload, digest, workflow_id, version),
        )
    finally:
        conn.execute(
            "ALTER TABLE workflow_versions ENABLE TRIGGER "
            f"{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}"
        )
    conn.commit()


def _row(conn, workflow_id: str, version: int) -> dict:
    cur = conn.execute(
        "SELECT definition_json, definition_digest FROM workflow_versions "
        "WHERE workflow_id = %s AND version = %s",
        (workflow_id, version),
    )
    got = cur.fetchone()
    return {"definition_json": got[0], "definition_digest": got[1]}


def test_legacy_binding_vocabulary_row_is_rewritten(test_db):
    converge_builtin_workflows(test_db)
    test_db.commit()
    row = _row(test_db, "dash", 1)
    definition = json.loads(row["definition_json"])
    definition["executor_bindings"] = [
        {
            ("executor_id" if key == "skill_id" else key): value
            for key, value in binding.items()
        }
        for binding in definition.pop("skill_bindings")
    ]
    legacy = canonical_definition_json(definition)
    _overwrite_row(test_db, "dash", 1, legacy, definition_digest(definition))

    converge_builtin_workflows(test_db)
    test_db.commit()

    healed = json.loads(_row(test_db, "dash", 1)["definition_json"])
    assert "executor_bindings" not in healed
    assert healed["skill_bindings"][0]["skill_id"]


def test_non_canonical_serialization_is_rewritten(test_db):
    converge_builtin_workflows(test_db)
    test_db.commit()
    row = _row(test_db, "issue", 1)
    definition = json.loads(row["definition_json"])
    scrambled = json.dumps(definition, ensure_ascii=False,
                           separators=(",", ":"), sort_keys=False)
    _overwrite_row(test_db, "issue", 1, scrambled, row["definition_digest"])

    converge_builtin_workflows(test_db)
    test_db.commit()

    healed = _row(test_db, "issue", 1)
    assert healed["definition_json"] == canonical_definition_json(definition)


def test_real_definition_drift_still_refuses(test_db):
    converge_builtin_workflows(test_db)
    test_db.commit()
    row = _row(test_db, "issue", 1)
    definition = json.loads(row["definition_json"])
    definition["stages"] = definition["stages"][:-1]
    _overwrite_row(
        test_db, "issue", 1,
        canonical_definition_json(definition),
        definition_digest(definition),
    )

    with pytest.raises(WorkflowRegistryError):
        converge_builtin_workflows(test_db)
    test_db.rollback()


def test_rewrite_rearms_the_immutability_trigger(test_db):
    converge_builtin_workflows(test_db)
    test_db.commit()
    row = _row(test_db, "dash", 1)
    definition = json.loads(row["definition_json"])
    scrambled = json.dumps(definition, ensure_ascii=False,
                           separators=(",", ":"), sort_keys=False)
    _overwrite_row(test_db, "dash", 1, scrambled, row["definition_digest"])
    converge_builtin_workflows(test_db)
    test_db.commit()

    with pytest.raises(Exception, match="immutable"):
        test_db.execute(
            "UPDATE workflow_versions SET definition_digest = 'x' "
            "WHERE workflow_id = %s AND version = %s",
            ("dash", 1),
        )
    test_db.rollback()

