"""Claims-topic packet recipe regressions.

Sibling of :mod:`test_schema_api_context`; the raw diagnostic path-claim
conflict recipe stays executable against the canonical columns.
"""

from __future__ import annotations

import sqlite3

from yoke_core.domain.schema_api_context_commands_claims import CLAIMS_COMMANDS


def test_specific_path_conflict_recipe_executes_against_canonical_columns() -> None:
    """The packet's raw diagnostic join stays executable against the schema."""
    entry = next(
        command
        for command in CLAIMS_COMMANDS
        if command["purpose"] == "Find conflicts on specific paths (SQL)"
    )
    recipe = str(entry["recipe"])
    sql = recipe.partition('yoke db read "')[2].rsplit('"', 1)[0]

    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE path_claims (
          id INTEGER PRIMARY KEY, owner_kind TEXT NOT NULL,
          owner_item_id INTEGER NOT NULL, state TEXT NOT NULL
        );
        CREATE TABLE path_targets (
          id INTEGER PRIMARY KEY, path_string TEXT NOT NULL
        );
        CREATE TABLE path_claim_targets (
          id INTEGER PRIMARY KEY,
          claim_id INTEGER NOT NULL REFERENCES path_claims(id),
          target_id INTEGER NOT NULL REFERENCES path_targets(id)
        );
        INSERT INTO path_claims (id, owner_kind, owner_item_id, state)
          VALUES (7, 'item', 42, 'active');
        INSERT INTO path_targets (id, path_string)
          VALUES (9, '<project-source-path>/foo.py');
        INSERT INTO path_claim_targets (id, claim_id, target_id)
          VALUES (11, 7, 9);
        """
    )

    assert conn.execute(sql).fetchall() == [
        (7, "item", 42, "active", "<project-source-path>/foo.py")
    ]
