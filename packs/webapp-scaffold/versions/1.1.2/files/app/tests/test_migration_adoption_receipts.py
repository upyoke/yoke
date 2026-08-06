"""Trusted legacy adoption leaves immutable, artifact-bound evidence."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys

import pytest


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

from db.migrations import migrate as migration_runner  # noqa: E402
from db.migrations.content_identity import RECEIPT_GUARDS  # noqa: E402


SOURCE_COMMIT = "b" * 40
SOURCE_SHA256 = "a" * 64


def _migration(directory):
    path = directory / "0001_existing.py"
    path.write_text(
        "def apply(conn):\n"
        "    raise AssertionError('adoption must not replay')\n"
        "def invariants(conn):\n"
        "    assert conn.execute('SELECT value FROM marks').fetchone()[0] == 'ok'\n",
        encoding="utf-8",
    )
    return path


def _canonical_sha256(payload) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _manifest(path, module):
    payload = {
        "schema_version": 1,
        "artifact": {
            "engine_version": "1.0.0",
            "source_artifact": "sample-app-1.0.0",
            "source_sha256": SOURCE_SHA256,
            "source_commit": SOURCE_COMMIT,
        },
        "entries": [
            {
                "name": "0001_existing",
                "content_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
            }
        ],
    }
    digest = _canonical_sha256(payload)
    document = {**payload, "manifest_sha256": digest}
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path, digest


def _adoption_args(
    manifest_sha256, *, source_commit=SOURCE_COMMIT, source_sha256=SOURCE_SHA256,
) -> dict:
    return {
        "source_commit": source_commit,
        "source_sha256": source_sha256,
        "manifest_sha256": manifest_sha256,
        "adopted_by": "test-operator",
    }


def _legacy_database(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE marks (value TEXT)")
    conn.execute("INSERT INTO marks VALUES ('ok')")
    conn.execute(
        "CREATE TABLE schema_version ("
        "migration_name TEXT PRIMARY KEY, version INTEGER UNIQUE, "
        "applied_at DATETIME DEFAULT (datetime('now')), "
        "minimum_serving_version TEXT, content_sha256 TEXT)"
    )
    conn.execute(
        "INSERT INTO schema_version (migration_name, version) "
        "VALUES ('0001_existing', 1)"
    )
    conn.commit()
    conn.close()


def _assert_no_evidence(database) -> None:
    conn = sqlite3.connect(database)
    assert conn.execute(
        "SELECT migration_name, content_sha256 FROM schema_version"
    ).fetchone() == ("0001_existing", None)
    assert conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='migration_adoption_receipts'"
    ).fetchone() is None
    conn.close()


@pytest.mark.parametrize(
    ("trusted_commit", "trusted_source_sha256", "message"),
    [
        ("c" * 40, SOURCE_SHA256, "source_commit does not match"),
        (SOURCE_COMMIT, "c" * 64, "source_sha256 does not match"),
    ],
)
def test_wrong_trusted_artifact_identity_refuses_without_evidence(
    tmp_path, monkeypatch, trusted_commit, trusted_source_sha256, message,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _migration(history)
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    _legacy_database(database)
    manifest, manifest_sha256 = _manifest(tmp_path / "adopt.json", module)

    with pytest.raises(RuntimeError, match=message):
        migration_runner.migrate(
            db_path=database,
            running_version="1.0.0",
            adoption_manifest=manifest,
            **_adoption_args(
                manifest_sha256,
                source_commit=trusted_commit,
                source_sha256=trusted_source_sha256,
            ),
        )

    _assert_no_evidence(database)


def test_recomputed_tampered_manifest_refuses_pinned_digest(
    tmp_path, monkeypatch,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _migration(history)
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    _legacy_database(database)
    manifest, trusted_manifest_sha256 = _manifest(tmp_path / "adopt.json", module)
    tampered = json.loads(manifest.read_text())
    tampered["artifact"]["source_artifact"] = "tampered-app-1.0.0"
    payload = {
        key: tampered[key] for key in ("schema_version", "artifact", "entries")
    }
    tampered["manifest_sha256"] = _canonical_sha256(payload)
    manifest.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(RuntimeError, match="Trusted manifest SHA256"):
        migration_runner.migrate(
            db_path=database, running_version="1.0.0",
            adoption_manifest=manifest,
            **_adoption_args(trusted_manifest_sha256),
        )

    _assert_no_evidence(database)


def test_empty_non_null_digest_is_mismatch_not_adoption(tmp_path, monkeypatch) -> None:
    history = tmp_path / "history"
    history.mkdir()
    _migration(history)
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    _legacy_database(database)
    conn = sqlite3.connect(database)
    conn.execute("UPDATE schema_version SET content_sha256='' WHERE version=1")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="content identity mismatch"):
        migration_runner.migrate(db_path=database, running_version="1.0.0")

    conn = sqlite3.connect(database)
    assert conn.execute(
        "SELECT content_sha256 FROM schema_version WHERE version=1"
    ).fetchone() == ("",)
    conn.close()


def test_adoption_fills_only_missing_name_and_preserves_digest(
    tmp_path, monkeypatch,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _migration(history)
    digest = hashlib.sha256(module.read_bytes()).hexdigest()
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    _legacy_database(database)
    conn = sqlite3.connect(database)
    conn.execute(
        "UPDATE schema_version SET migration_name=NULL, content_sha256=?",
        (digest,),
    )
    conn.commit()
    conn.close()
    manifest, manifest_sha256 = _manifest(tmp_path / "adopt.json", module)

    migration_runner.migrate(
        db_path=database, running_version="1.0.0",
        adoption_manifest=manifest, **_adoption_args(manifest_sha256),
    )

    conn = sqlite3.connect(database)
    assert conn.execute(
        "SELECT migration_name, content_sha256 FROM schema_version"
    ).fetchone() == ("0001_existing", digest)
    conn.close()


def test_successful_adoption_receipt_is_append_only(tmp_path, monkeypatch) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _migration(history)
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    _legacy_database(database)
    manifest, manifest_digest = _manifest(tmp_path / "adopt.json", module)

    result = migration_runner.migrate(
        db_path=database,
        running_version="1.0.0",
        adoption_manifest=manifest,
        **_adoption_args(manifest_digest),
    )

    receipt = result["data"]["adoption_receipt"]
    assert receipt["manifest_sha256"] == manifest_digest
    assert receipt["source_sha256"] == SOURCE_SHA256
    assert receipt["source_commit"] == SOURCE_COMMIT
    assert receipt["adopted_by"] == "test-operator"
    conn = sqlite3.connect(database)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(
            "UPDATE migration_adoption_receipts SET source_commit='changed'"
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM migration_adoption_receipts")
    conn.rollback()
    row = conn.execute(
        "SELECT manifest_sha256, source_commit, adopted_by, adopted_entries_json "
        "FROM migration_adoption_receipts"
    ).fetchone()
    conn.close()
    assert row == (
        manifest_digest, SOURCE_COMMIT, "test-operator",
        '[{"content_sha256":"' + hashlib.sha256(module.read_bytes()).hexdigest()
        + '","name":"0001_existing"}]',
    )


@pytest.mark.parametrize("dropped_guard", sorted(RECEIPT_GUARDS))
def test_missing_receipt_guard_blocks_readiness_and_adoption_restores_it(
    tmp_path, monkeypatch, dropped_guard,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _migration(history)
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    _legacy_database(database)
    manifest, manifest_digest = _manifest(tmp_path / "adopt.json", module)
    migration_runner.migrate(
        db_path=database, running_version="1.0.0",
        adoption_manifest=manifest, **_adoption_args(manifest_digest),
    )
    conn = sqlite3.connect(database)
    conn.execute(f"DROP TRIGGER {dropped_guard}")
    conn.commit()
    state = migration_runner.migration_state(conn, running_version="1.0.0")
    conn.close()
    assert state["ready"] is False
    assert state["adoption_receipt_guards_ready"] is False
    assert state["missing_adoption_receipt_guards"] == [dropped_guard]

    with pytest.raises(RuntimeError, match="readiness failed"):
        migration_runner.migrate(db_path=database, running_version="1.0.0")

    repaired = migration_runner.migrate(
        db_path=database, running_version="1.0.0",
        adoption_manifest=manifest, **_adoption_args(manifest_digest),
    )
    assert repaired["data"]["adopted"] == []
    assert repaired["data"]["adoption_receipt"] is None
    assert repaired["data"]["adoption_receipt_guards_ready"] is True
    conn = sqlite3.connect(database)
    installed = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='migration_adoption_receipts'"
        )
    }
    conn.close()
    assert installed == set(RECEIPT_GUARDS)


def test_wrong_receipt_guard_body_is_detected_and_replaced(
    tmp_path, monkeypatch,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _migration(history)
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    _legacy_database(database)
    manifest, digest = _manifest(tmp_path / "adopt.json", module)
    args = _adoption_args(digest)
    migration_runner.migrate(
        db_path=database, running_version="1.0.0",
        adoption_manifest=manifest, **args,
    )
    guard = "migration_adoption_receipts_no_update"
    conn = sqlite3.connect(database)
    conn.execute(f"DROP TRIGGER {guard}")
    conn.execute(
        f"CREATE TRIGGER {guard} BEFORE UPDATE ON "
        "migration_adoption_receipts BEGIN SELECT 1; END"
    )
    assert migration_runner.migration_state(
        conn, running_version="1.0.0",
    )["missing_adoption_receipt_guards"] == [guard]
    conn.close()

    migration_runner.migrate(
        db_path=database, running_version="1.0.0",
        adoption_manifest=manifest, **args,
    )
    conn = sqlite3.connect(database)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE migration_adoption_receipts SET adopted_by='x'")
    conn.close()
