"""Atomic refusal when migration adoption evidence races or is mutable."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from runtime.api.domain.migration_artifact_trust_test_helpers import (
    artifact_verifier_for,
)
from runtime.api.domain.migration_boot_test_helpers import connection
from yoke_core.domain.migration_content_adoption import (
    MigrationContentAdoptionError,
    adopt_legacy_content_identities,
)
from yoke_core.domain.migration_content_schema import adoption_evidence_verifier
from yoke_core.domain.migration_history import ordered_entries
from yoke_core.domain.migration_history_manifest import (
    ArtifactIdentity,
    manifest_from_history,
)
from yoke_core.domain.migration_yoke_ledger import (
    YOKE_ADOPTION_EVIDENCE_CONTRACT,
    YOKE_ADOPTION_EVIDENCE_TABLE,
    YOKE_LEDGER_CONTRACT,
    adopt_yoke_legacy_content_identities,
    write_yoke_adoption_evidence,
)


SOURCE_COMMIT = "d" * 40


def _adoption_case(tmp_path: Path):
    (tmp_path / "0001_existing.py").write_text(
        "def apply(conn):\n    pass\n\n"
        "def invariants(conn):\n"
        '    assert conn.execute("SELECT content_sha256 FROM '
        "applied_migrations WHERE migration_name='0001_existing'\")"
        ".fetchone() == (None,)\n",
        encoding="utf-8",
    )
    history = ordered_entries(tmp_path)
    artifact = ArtifactIdentity(
        "1.2.3",
        "yoke_core-1.2.3.whl",
        "a" * 64,
        SOURCE_COMMIT,
    )
    return history, artifact, manifest_from_history(history, artifact)


def test_existing_evidence_conflict_rolls_back_ledger_digest(
    tmp_path: Path,
) -> None:
    conn = connection()
    history, artifact, manifest = _adoption_case(tmp_path)
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by, content_sha256) "
        "VALUES ('0001_existing', 'now', 'legacy', NULL)"
    )
    conn.execute(
        f"INSERT INTO {YOKE_ADOPTION_EVIDENCE_TABLE} VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "0001_existing",
            "f" * 64,
            "older",
            "older.whl",
            "e" * 64,
            "e" * 40,
            "e" * 64,
            "operator:other",
            "2026-08-05T00:00:00Z",
        ),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        adopt_yoke_legacy_content_identities(
            conn,
            history=history,
            manifest=manifest,
            artifact=artifact,
            expected_manifest_sha256=manifest.content_sha256,
            artifact_verifier=artifact_verifier_for(manifest),
            adopted_by="operator:test",
        )

    assert conn.execute("SELECT content_sha256 FROM applied_migrations").fetchone() == (
        None,
    )
    assert conn.execute(
        f"SELECT content_sha256 FROM {YOKE_ADOPTION_EVIDENCE_TABLE}"
    ).fetchone() == ("f" * 64,)


def test_dropped_evidence_guard_refuses_before_ledger_write(
    tmp_path: Path,
) -> None:
    conn = connection()
    history, artifact, manifest = _adoption_case(tmp_path)
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by, content_sha256) "
        "VALUES ('0001_existing', 'now', 'legacy', NULL)"
    )
    triggers = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
        (YOKE_ADOPTION_EVIDENCE_CONTRACT.table,),
    ).fetchall()
    for row in triggers:
        conn.execute(f"DROP TRIGGER {row[0]}")
    conn.commit()

    with pytest.raises(MigrationContentAdoptionError, match="database guards"):
        adopt_yoke_legacy_content_identities(
            conn,
            history=history,
            manifest=manifest,
            artifact=artifact,
            expected_manifest_sha256=manifest.content_sha256,
            artifact_verifier=artifact_verifier_for(manifest),
            adopted_by="operator:test",
        )

    assert conn.execute("SELECT content_sha256 FROM applied_migrations").fetchone() == (
        None,
    )


def test_racing_digest_update_rolls_back_new_evidence(tmp_path: Path) -> None:
    conn = connection()
    history, artifact, manifest = _adoption_case(tmp_path)
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by, content_sha256) "
        "VALUES ('0001_existing', 'now', 'legacy', NULL)"
    )
    conn.commit()

    def write_evidence_then_race(database, records) -> None:
        write_yoke_adoption_evidence(database, records)
        database.execute(
            "UPDATE applied_migrations SET content_sha256 = ? WHERE migration_name = ?",
            (records[0].content_sha256, records[0].entry_name),
        )

    with pytest.raises(MigrationContentAdoptionError, match="changed before adoption"):
        adopt_legacy_content_identities(
            conn,
            history=history,
            ledger=YOKE_LEDGER_CONTRACT,
            manifest=manifest,
            artifact=artifact,
            expected_manifest_sha256=manifest.content_sha256,
            artifact_verifier=artifact_verifier_for(manifest),
            adopted_by="operator:test",
            write_evidence=write_evidence_then_race,
            verify_evidence_immutability=adoption_evidence_verifier(
                YOKE_LEDGER_CONTRACT,
                YOKE_ADOPTION_EVIDENCE_CONTRACT,
            ),
        )

    assert conn.execute("SELECT content_sha256 FROM applied_migrations").fetchone() == (
        None,
    )
    assert conn.execute(
        f"SELECT count(*) FROM {YOKE_ADOPTION_EVIDENCE_TABLE}"
    ).fetchone() == (0,)
