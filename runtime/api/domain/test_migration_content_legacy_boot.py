"""Legacy-ledger rollout ordering before content-aware Yoke boot."""

from __future__ import annotations

import sqlite3

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table
from yoke_core.domain.migration_boot_apply import apply_pending
from yoke_core.domain.migration_history import history_dir, ordered_entries
from yoke_core.domain.migration_yoke_ledger import (
    YOKE_LEDGER_CONTRACT,
    ensure_yoke_migration_ledger,
    yoke_migration_content_schema_is_prepared,
)

CONTENT_IDENTITY_ENTRY = "0006_migration_content_identity"


def test_yoke_legacy_boot_converges_digest_before_applying_entry_0006() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE applied_migrations ("
        "migration_name TEXT PRIMARY KEY, applied_at TEXT NOT NULL, "
        "applied_by TEXT, minimum_serving_version TEXT)"
    )
    # This test is about one entry: the content-identity one. Naming it rather
    # than taking whatever is newest keeps a later append from re-pointing the
    # subject at an unrelated entry.
    full_history = ordered_entries(history_dir(migration_history_package))
    subject = next(
        index for index, entry in enumerate(full_history)
        if entry.name == CONTENT_IDENTITY_ENTRY
    )
    history = full_history[:subject + 1]
    for entry in history[:-1]:
        conn.execute(
            "INSERT INTO applied_migrations "
            "(migration_name, applied_at, applied_by) VALUES (?, 'now', 'legacy')",
            (entry.name,),
        )
    ensure_migration_audit_table(conn)
    conn.commit()

    # create_governed_tables performs this additive convergence before
    # converge_migration_history calls the content-aware boot kernel.
    ensure_yoke_migration_ledger(conn)
    assert not yoke_migration_content_schema_is_prepared(conn)
    outcome = apply_pending(
        conn,
        history=history,
        ledger=YOKE_LEDGER_CONTRACT,
        applied_by="boot-converge",
        running_version="",
        external_restore_point="snapshot:legacy-yoke",
    )

    assert outcome.applied == (history[-1].name,)
    assert yoke_migration_content_schema_is_prepared(conn)
    rows = conn.execute(
        "SELECT migration_name, content_sha256 FROM applied_migrations "
        "ORDER BY migration_name"
    ).fetchall()
    assert all(digest is None for _name, digest in rows[:-1])
    assert rows[-1] == (history[-1].name, history[-1].content_sha256)
