"""Legacy identity adoption is exact, invariant-gated, and atomic."""

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
from tests.conftest import (  # noqa: E402
    SOURCE_COMMIT,
    SOURCE_SHA256,
    adoption_arguments as _adoption_args,
    write_adoption_manifest as _manifest,
)


def _entry(directory, name: str, source: str):
    path = directory / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    return path


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ledger(conn) -> None:
    conn.execute(
        "CREATE TABLE schema_version ("
        "migration_name TEXT PRIMARY KEY, version INTEGER UNIQUE, "
        "applied_at DATETIME DEFAULT (datetime('now')), "
        "minimum_serving_version TEXT, content_sha256 TEXT)"
    )


def test_exact_manifest_adopts_and_records_trusted_artifact_identity(
    tmp_path,
    monkeypatch,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _entry(
        history,
        "0001_existing",
        "def apply(conn):\n"
        "    raise AssertionError('adoption must not execute apply')\n"
        "def invariants(conn):\n"
        "    assert conn.execute('SELECT value FROM marks').fetchone()[0] == 'ok'\n",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    conn = sqlite3.connect(database)
    conn.execute("CREATE TABLE marks (value TEXT)")
    conn.execute("INSERT INTO marks VALUES ('ok')")
    _ledger(conn)
    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    conn.commit()
    conn.close()
    manifest, manifest_sha256 = _manifest(
        tmp_path / "adopt.json",
        {"0001_existing": _digest(module)},
    )

    result = migration_runner.migrate(
        db_path=database,
        running_version="1.0.0",
        adoption_manifest=manifest,
        **_adoption_args(manifest_sha256),
    )

    conn = sqlite3.connect(database)
    row = conn.execute(
        "SELECT migration_name, content_sha256 FROM schema_version"
    ).fetchone()
    receipt = conn.execute(
        "SELECT manifest_sha256, source_sha256, source_commit, adopted_by, "
        "adopted_entries_json FROM migration_adoption_receipts"
    ).fetchone()
    conn.close()
    assert row == ("0001_existing", _digest(module))
    assert receipt[:4] == (
        manifest_sha256,
        SOURCE_SHA256,
        SOURCE_COMMIT,
        "test-operator",
    )
    assert json.loads(receipt[4]) == [
        {
            "content_sha256": _digest(module),
            "minimum_serving_version": None,
            "name": "0001_existing",
        }
    ]
    assert result["data"]["adopted"] == ["0001_existing"]
    assert result["data"]["applied"] == []
    assert result["data"]["ready"] is True


def test_wrong_entry_digest_refuses_every_identity_update(
    tmp_path,
    monkeypatch,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    first = _entry(
        history,
        "0001_first",
        "def apply(conn):\n    pass\n"
        "def invariants(conn):\n    conn.execute('SELECT 1').fetchone()\n",
    )
    _entry(
        history,
        "0002_second",
        "def apply(conn):\n    pass\n"
        "def invariants(conn):\n    conn.execute('SELECT 1').fetchone()\n",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    conn = sqlite3.connect(database)
    _ledger(conn)
    conn.execute(
        "INSERT INTO schema_version VALUES ('0001_first', 1, NULL, NULL, NULL)"
    )
    conn.execute(
        "INSERT INTO schema_version VALUES ('0002_second', 2, NULL, NULL, NULL)"
    )
    conn.commit()
    conn.close()
    manifest, manifest_sha256 = _manifest(
        tmp_path / "wrong.json",
        {"0001_first": _digest(first), "0002_second": "0" * 64},
    )

    with pytest.raises(RuntimeError, match="does not match the exact"):
        migration_runner.migrate(
            db_path=database,
            running_version="1.0.0",
            adoption_manifest=manifest,
            **_adoption_args(manifest_sha256),
        )

    conn = sqlite3.connect(database)
    rows = conn.execute(
        "SELECT content_sha256 FROM schema_version ORDER BY version"
    ).fetchall()
    conn.close()
    assert rows == [(None,), (None,)]


def test_project_state_verifier_adopts_apply_only_permanent_module(
    tmp_path,
    monkeypatch,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _entry(
        history,
        "0001_existing",
        "def apply(conn):\n    raise AssertionError('adoption must not replay')\n",
    )
    permanent_bytes = module.read_bytes()
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    conn = sqlite3.connect(database)
    conn.execute("CREATE TABLE marks (value TEXT)")
    conn.execute("INSERT INTO marks VALUES ('ok')")
    _ledger(conn)
    conn.execute(
        "INSERT INTO schema_version (migration_name, version) VALUES (?, ?)",
        (
            "0001_existing",
            1,
        ),
    )
    conn.commit()
    conn.close()
    manifest, manifest_sha256 = _manifest(
        tmp_path / "adopt.json",
        {"0001_existing": _digest(module)},
    )
    verified = []

    def verify_existing_state(conn):
        assert conn.execute("SELECT value FROM marks").fetchone()[0] == "ok"
        verified.append("0001_existing")

    result = migration_runner.migrate(
        db_path=database,
        running_version="1.0.0",
        adoption_manifest=manifest,
        adoption_state_verifiers={"0001_existing": verify_existing_state},
        **_adoption_args(manifest_sha256),
    )

    assert module.read_bytes() == permanent_bytes
    assert verified == ["0001_existing"]
    assert result["data"]["adopted"] == ["0001_existing"]


@pytest.mark.parametrize(
    ("registry", "message"),
    [
        ({"0002_unknown": lambda conn: None}, "unknown=\\['0002_unknown'\\]"),
        ({"0001_existing": "not-callable"}, "non_callable=\\['0001_existing'\\]"),
    ],
)
def test_invalid_state_verifier_registry_refuses_before_identity_mutation(
    tmp_path,
    monkeypatch,
    registry,
    message,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _entry(
        history,
        "0001_existing",
        "def apply(conn):\n    raise AssertionError('adoption must not replay')\n",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    conn = sqlite3.connect(database)
    _ledger(conn)
    conn.execute(
        "INSERT INTO schema_version (migration_name, version) VALUES (?, ?)",
        ("0001_existing", 1),
    )
    conn.commit()
    conn.close()
    manifest, manifest_sha256 = _manifest(
        tmp_path / "adopt.json",
        {"0001_existing": _digest(module)},
    )

    with pytest.raises(RuntimeError, match=message):
        migration_runner.migrate(
            db_path=database,
            running_version="1.0.0",
            adoption_manifest=manifest,
            adoption_state_verifiers=registry,
            **_adoption_args(manifest_sha256),
        )

    conn = sqlite3.connect(database)
    row = conn.execute(
        "SELECT migration_name, content_sha256 FROM schema_version"
    ).fetchone()
    receipt_table = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='migration_adoption_receipts'"
    ).fetchone()
    conn.close()
    assert row == ("0001_existing", None)
    assert receipt_table is None


def test_failed_state_equivalence_rolls_back_identity_and_receipt(
    tmp_path,
    monkeypatch,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _entry(
        history,
        "0001_expected_state",
        "def apply(conn):\n    pass\n"
        "def invariants(conn):\n"
        "    assert conn.execute('SELECT COUNT(*) FROM marks').fetchone()[0] == 1\n",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    conn = sqlite3.connect(database)
    conn.execute("CREATE TABLE marks (value TEXT)")
    _ledger(conn)
    conn.execute(
        "INSERT INTO schema_version (migration_name, version) VALUES (?, ?)",
        ("0001_expected_state", 1),
    )
    conn.commit()
    conn.close()
    manifest, manifest_sha256 = _manifest(
        tmp_path / "state.json",
        {"0001_expected_state": _digest(module)},
    )

    with pytest.raises(AssertionError):
        migration_runner.migrate(
            db_path=database,
            running_version="1.0.0",
            adoption_manifest=manifest,
            **_adoption_args(manifest_sha256),
        )

    conn = sqlite3.connect(database)
    row = conn.execute(
        "SELECT migration_name, content_sha256 FROM schema_version"
    ).fetchone()
    receipt_table = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='migration_adoption_receipts'"
    ).fetchone()
    conn.close()
    assert row == ("0001_expected_state", None)
    assert receipt_table is None
