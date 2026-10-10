"""Atomic refusal when migration adoption evidence races or is mutable."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant

from runtime.api.domain.migration_artifact_trust_test_helpers import (
    artifact_verifier_for,
)
from runtime.api.domain.migration_boot_test_helpers import connection
from yoke_core.domain.migration_content_adoption import (
    AdoptionRecord,
    MigrationContentAdoptionError,
    adopt_legacy_content_identities,
)
from yoke_core.domain.migration_content_schema import (
    adoption_evidence_verifier,
    write_adoption_evidence,
)
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


def test_adoption_authority_is_lazy_until_artifact_verification(
    tmp_path: Path,
) -> None:
    conn = connection()
    history, artifact, manifest = _adoption_case(tmp_path)
    statements: list[str] = []
    conn.set_trace_callback(statements.append)

    def forbidden_authority():
        raise AssertionError("transaction authority opened before artifact trust")

    with pytest.raises(MigrationContentAdoptionError, match="artifact verification"):
        adopt_legacy_content_identities(
            conn,
            history=history,
            ledger=YOKE_LEDGER_CONTRACT,
            manifest=manifest,
            artifact=artifact,
            expected_manifest_sha256=manifest.content_sha256,
            artifact_verifier=None,
            adopted_by="operator:test",
            write_evidence=lambda _conn, _records: None,
            verify_evidence_immutability=lambda _conn: True,
            transaction_authority=forbidden_authority,
        )

    assert statements == []


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


@pytest.mark.parametrize(
    "clock",
    [
        "1969-12-31T23:59:59.123456Z",
        "1970-01-01T05:29:59.123456+05:30",
        "1969-12-31T19:59:59.123456-04:00",
    ],
)
def test_adoption_generates_native_fact_until_sqlite_evidence_owner(tmp_path, clock):
    conn = connection()
    history, artifact, manifest = _adoption_case(tmp_path)
    conn.execute(
        "INSERT INTO applied_migrations (migration_name, applied_at, applied_by, content_sha256) VALUES ('0001_existing', 'now', 'legacy', NULL)"
    )
    conn.commit()
    records = adopt_yoke_legacy_content_identities(
        conn,
        history=history,
        manifest=manifest,
        artifact=artifact,
        expected_manifest_sha256=manifest.content_sha256,
        artifact_verifier=artifact_verifier_for(manifest),
        adopted_by="operator:test",
        adopted_at=clock,
    )
    assert records[0].adopted_at == parse_instant(clock)
    row = conn.execute(
        f"SELECT adopted_at,content_sha256,source_sha256,manifest_sha256 FROM {YOKE_ADOPTION_EVIDENCE_TABLE}"
    ).fetchone()
    assert row == (
        format_instant(clock),
        history[0].content_sha256,
        artifact.source_sha256,
        manifest.content_sha256,
    )


@pytest.mark.parametrize("microsecond", [0, 123456])
@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_adoption_evidence_sql_owner_binds_native_microseconds(
    test_db, zone, microsecond
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    clock = parse_instant("1970-01-01T05:29:59.123456+05:30").replace(
        microsecond=microsecond
    )
    supplied = clock.astimezone(timezone(timedelta(hours=5, minutes=30)))
    record = AdoptionRecord(
        "0001_native_clock",
        "a" * 64,
        "engine",
        "artifact",
        "b" * 64,
        "c" * 40,
        "d" * 64,
        "operator:test",
        supplied,
    )
    assert record.adopted_at == clock
    assert record.adopted_at.tzinfo is timezone.utc
    write_adoption_evidence(test_db, (record,), YOKE_ADOPTION_EVIDENCE_CONTRACT)
    row = test_db.execute(
        f"SELECT adopted_at,content_sha256,source_sha256 FROM {YOKE_ADOPTION_EVIDENCE_TABLE} WHERE migration_name=%s",
        (record.entry_name,),
    ).fetchone()
    assert tuple(row) == (clock, record.content_sha256, record.source_sha256)


@pytest.mark.parametrize(
    "clock",
    [
        None,
        0,
        False,
        datetime(1970, 1, 1),
        "1969-12-31T23:59:59.123456Z",
        "1970-01-01T05:29:59.123456+05:30",
        "",
        "1970-01-01",
        "1970-01-01T00:00:00",
        "1970-01-01T00:00:00-00:00",
    ],
)
def test_adoption_record_refuses_unverifiable_clock(clock):
    with pytest.raises(InvalidInstant):
        AdoptionRecord(
            "entry",
            "a" * 64,
            "engine",
            "artifact",
            "b" * 64,
            "c" * 40,
            "d" * 64,
            "operator:test",
            clock,
        )
