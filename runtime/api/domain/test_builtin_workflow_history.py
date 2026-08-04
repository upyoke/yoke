"""Convergence leaves a universe's stored definitions alone.

A universe's ``workflow_versions`` rows are its data. These assert the
properties that keeps that true: convergence makes the current definition
available and otherwise never rewrites, renumbers, deletes, or refuses to boot
over what is already stored.

The refusal is what these replaced. It compared each stored row against a
code-owned fixture *by version number*, so a universe that published on its own
schedule looked identical to a corrupted one, and boot being fail-hard turned
that into two fleet-wide outages.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_IDS,
    builtin_workflow_definition,
)
from yoke_core.domain.builtin_workflow_version_convergence import (
    unrecognized_builtin_versions,
)
from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)
from yoke_core.domain.workflow_registry import converge_builtin_workflows

_LEGACY_TS = "2026-07-28T00:00:00Z"


def _insert(conn, workflow_id: str, version: int, definition: dict) -> None:
    conn.execute(
        "INSERT INTO workflow_versions "
        "(workflow_id, version, definition_schema_version, definition_json, "
        "definition_digest, published_at, immutable_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            workflow_id,
            version,
            definition["schema_version"],
            canonical_definition_json(definition),
            definition_digest(definition),
            _LEGACY_TS,
            _LEGACY_TS,
        ),
    )


def _seed(conn, *, generations_per_workflow: int, start_at: int = 1) -> dict:
    """Seed each workflow with real published generations from the canon."""
    # TRUNCATE rather than DELETE: published rows are immutable and the row
    # trigger refuses to remove them, which is the guarantee under test.
    conn.execute("TRUNCATE workflows, workflow_versions RESTART IDENTITY CASCADE")
    stored: dict[str, list[tuple[int, str]]] = {}
    for workflow_id in BUILTIN_WORKFLOW_IDS:
        workflow = builtin_workflow_definition(workflow_id)["workflow"]
        conn.execute(
            "INSERT INTO workflows "
            "(id, name, description, source, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 'active', %s, %s)",
            (
                workflow["id"],
                workflow["name"],
                workflow["description"],
                workflow["source"],
                _LEGACY_TS,
                _LEGACY_TS,
            ),
        )
        rows = []
        generations = canon_generations(workflow_id)[:generations_per_workflow]
        for offset, generation in enumerate(generations):
            version = start_at + offset
            _insert(conn, workflow_id, version, generation.definition)
            rows.append((version, generation.digest))
        stored[workflow_id] = rows
    conn.commit()
    return stored


def _rows(conn, workflow_id: str) -> list[tuple[int, str]]:
    cursor = conn.execute(
        "SELECT version, definition_digest FROM workflow_versions "
        "WHERE workflow_id = %s ORDER BY version",
        (workflow_id,),
    )
    return [(int(v), str(d)) for v, d in cursor.fetchall()]


def test_converging_never_rewrites_a_stored_row(test_db) -> None:
    before = _seed(test_db, generations_per_workflow=3)

    converge_builtin_workflows(test_db)

    for workflow_id in BUILTIN_WORKFLOW_IDS:
        after = _rows(test_db, workflow_id)
        assert after[: len(before[workflow_id])] == before[workflow_id], (
            f"{workflow_id}: convergence altered rows the universe already held"
        )


def test_converging_appends_the_current_definition(test_db) -> None:
    _seed(test_db, generations_per_workflow=2)

    converge_builtin_workflows(test_db)

    for workflow_id in BUILTIN_WORKFLOW_IDS:
        current = builtin_workflow_definition(workflow_id)["definition"]
        digests = [digest for _, digest in _rows(test_db, workflow_id)]
        assert definition_digest(current) in digests


def test_a_universe_numbered_ahead_converges(test_db) -> None:
    """Stage numbering ran one ahead of prod for weeks. That is legal."""
    _seed(test_db, generations_per_workflow=3, start_at=7)

    converge_builtin_workflows(test_db)

    for workflow_id in BUILTIN_WORKFLOW_IDS:
        versions = [version for version, _ in _rows(test_db, workflow_id)]
        assert versions[:3] == [7, 8, 9], "existing numbering was disturbed"
        assert max(versions) == 10, "current definition did not append after them"


def test_an_unrecognized_definition_does_not_stop_the_boot(test_db) -> None:
    """The property whose absence caused both outages.

    A row the canon does not recognize is either a local customization or real
    corruption. Either way it is one universe's business, and must not prevent
    that universe -- or any other -- from starting.
    """
    _seed(test_db, generations_per_workflow=2)
    local = deepcopy(canon_generations("issue")[0].definition)
    local["policies"]["a_locally_added_policy"] = "chosen by this universe"
    _insert(test_db, "issue", 99, local)
    test_db.commit()

    converge_builtin_workflows(test_db)

    assert (99, definition_digest(local)) in _rows(test_db, "issue")


def test_unrecognized_definitions_are_reported(test_db) -> None:
    _seed(test_db, generations_per_workflow=2)
    assert unrecognized_builtin_versions(test_db) == []

    local = deepcopy(canon_generations("dash")[0].definition)
    local["policies"]["a_locally_added_policy"] = "chosen by this universe"
    _insert(test_db, "dash", 42, local)
    test_db.commit()

    findings = unrecognized_builtin_versions(test_db)
    assert [(f["workflow_id"], f["version"]) for f in findings] == [("dash", 42)]


@pytest.mark.parametrize("generations", (1, 2, 3))
def test_convergence_is_idempotent_from_every_shape(test_db, generations: int) -> None:
    _seed(test_db, generations_per_workflow=generations)

    converge_builtin_workflows(test_db)
    once = {w: _rows(test_db, w) for w in BUILTIN_WORKFLOW_IDS}
    converge_builtin_workflows(test_db)

    assert {w: _rows(test_db, w) for w in BUILTIN_WORKFLOW_IDS} == once
