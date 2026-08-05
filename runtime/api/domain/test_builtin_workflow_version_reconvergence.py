"""Convergence recognizes stored rows; it never rewrites them.

Existing universes hold built-in definition rows written in earlier
vocabularies or through different serializers. Convergence reads them, decides
whether the current definition is already present, and appends it when it is
not. It does not heal, renumber, or refuse -- a row it cannot recognize is
reported for that one universe rather than raised at a boot that runs for
every tenant.
"""

from __future__ import annotations

import json

from yoke_core.domain.builtin_workflow_version_convergence import (
    unrecognized_builtin_versions,
)
from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)
from yoke_core.domain.workflow_registry import (
    converge_builtin_workflows,
    list_current_workflows,
)
from yoke_core.domain.workflow_schema import (
    WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER,
)


def _overwrite_row(conn, workflow_id: str, version: int, payload: str,
                   digest: str) -> None:
    """Forge a stored row the way an outside writer once did.

    Published rows are immutable, so reaching past the trigger is the only way
    to reproduce what a governed migration did to these rows in production.
    """
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


def _versions(conn, workflow_id: str) -> list[int]:
    row = next(
        candidate for candidate in list_current_workflows(conn)
        if candidate["id"] == workflow_id
    )
    return [version["version"] for version in row["versions"]]


def test_a_legacy_vocabulary_row_is_kept_and_reported(test_db):
    """An older vocabulary is history, not damage to be repaired."""
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

    # Left exactly as stored.
    assert _row(test_db, "dash", 1)["definition_json"] == legacy
    # The current definition arrives beside it instead of on top of it.
    assert _versions(test_db, "dash") == [1, 2]
    assert ("dash", 1) in [
        (finding["workflow_id"], finding["version"])
        for finding in unrecognized_builtin_versions(test_db)
    ]


def test_a_differently_serialized_row_is_recognized_not_duplicated(test_db):
    """Recognition is by digest, so serialization cannot manufacture drift.

    A governed migration rewrote these rows through a different serializer
    once. Under byte comparison that reads as a definition the universe does
    not have, and convergence would append a second copy of what it already
    held.
    """
    converge_builtin_workflows(test_db)
    test_db.commit()
    row = _row(test_db, "issue", 1)
    definition = json.loads(row["definition_json"])
    scrambled = json.dumps(
        definition, ensure_ascii=False, indent=2, sort_keys=False,
    )
    assert scrambled != row["definition_json"]
    _overwrite_row(test_db, "issue", 1, scrambled, row["definition_digest"])

    converge_builtin_workflows(test_db)
    test_db.commit()

    assert _versions(test_db, "issue") == [1]
    assert _row(test_db, "issue", 1)["definition_json"] == scrambled
    assert unrecognized_builtin_versions(test_db) == []


def test_real_definition_drift_is_reported_not_refused(test_db):
    """The behavior change that ended two fleet-wide outages."""
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

    converge_builtin_workflows(test_db)
    test_db.commit()

    assert ("issue", 1) in [
        (finding["workflow_id"], finding["version"])
        for finding in unrecognized_builtin_versions(test_db)
    ]
    assert _versions(test_db, "issue") == [1, 2]


def test_published_rows_stay_immutable_after_convergence(test_db):
    converge_builtin_workflows(test_db)
    test_db.commit()

    try:
        test_db.execute(
            "UPDATE workflow_versions SET definition_digest = 'x' "
            "WHERE workflow_id = %s AND version = %s",
            ("dash", 1),
        )
    except Exception as refusal:
        assert "immutable" in str(refusal)
    else:
        raise AssertionError("published rows must refuse updates")
    test_db.rollback()
