"""Doctor reads the selected project's history and database, never Yoke's."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from yoke_core.engines import doctor_project_migration_state as resolution
from yoke_core.engines.doctor_hc_pending_migrations import hc_pending_migrations
from yoke_core.engines.doctor_hc_project_migration_ledger import (
    hc_project_migration_ledger_contract,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _capability(
    *, ledger: bool = True, artifact_version_env_var: str | None = None,
) -> dict:
    config = {
        "modules_dir": "app/db/migrations",
        "connection_env_var": "EXTERNAL_DB_PATH",
    }
    if ledger:
        config["ledger"] = {
            "table": "schema_version",
            "entry_column": "migration_name",
            "semantics": "membership",
            "serving_floor_column": "minimum_serving_version",
        }
    if artifact_version_env_var:
        config["artifact_version_env_var"] = artifact_version_env_var
    return {
        "default_model": "primary",
        "models": {
            "primary": {
                "authoritative_db": {
                    "kind": "sqlite_file",
                    "location": {"path": "app/data/app.db"},
                },
                "validation_surface": {
                    "kind": "worktree_local_sqlite",
                    "provisioning": {
                        "path": ".yoke/validation.db",
                        "recipe": "webapp_sqlite_empty",
                    },
                },
                "runner": {
                    "kind": "governed_migration_module",
                    "config": config,
                },
            },
        },
    }


def _control(settings: dict) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, name TEXT, "
        "public_item_prefix TEXT)"
    )
    conn.execute(
        "CREATE TABLE project_capabilities "
        "(project_id INTEGER, type TEXT, settings TEXT)"
    )
    conn.execute("INSERT INTO projects VALUES (7, 'external', 'External', 'EXT')")
    conn.execute(
        "INSERT INTO project_capabilities VALUES (7, 'migration_model', ?)",
        (json.dumps(settings),),
    )
    # A level Yoke-shaped control-plane ledger is the false-green trap. The
    # external check must never consult it.
    conn.execute(
        "CREATE TABLE applied_migrations (migration_name TEXT PRIMARY KEY)"
    )
    conn.execute("INSERT INTO applied_migrations VALUES ('0001_external')")
    return conn


def _checkout(
    tmp_path: Path, *, create_ledger: bool = True,
    entry_name: str = "0001_external",
) -> Path:
    root = tmp_path / "external"
    history = root / "app" / "db" / "migrations"
    history.mkdir(parents=True)
    (history / f"{entry_name}.py").write_text(
        "MINIMUM_SERVING_VERSION = '2.0.0'\n"
        "def apply(conn):\n"
        "    pass\n"
    )
    database = root / "app" / "data" / "app.db"
    database.parent.mkdir(parents=True)
    db = sqlite3.connect(database)
    if create_ledger:
        db.execute(
            "CREATE TABLE schema_version ("
            "migration_name TEXT PRIMARY KEY, "
            "minimum_serving_version TEXT)"
        )
    db.close()
    return root


def _run(check, conn) -> object:
    rec = RecordCollector()
    check(conn, DoctorArgs(project="external"), rec)
    assert len(rec.results) == 1
    return rec.results[0]


def test_external_project_cannot_pass_from_the_control_plane_ledger(
    tmp_path: Path, monkeypatch,
) -> None:
    control = _control(_capability())
    checkout = _checkout(tmp_path, create_ledger=False)
    monkeypatch.setattr(resolution, "checkout_for_project", lambda *_: checkout)

    record = _run(hc_pending_migrations, control)

    assert record.result == "WARN"
    assert "schema_version" in record.detail
    assert "applied_migrations" not in record.detail


def test_external_project_reports_its_own_pending_history(
    tmp_path: Path, monkeypatch,
) -> None:
    control = _control(_capability())
    checkout = _checkout(tmp_path)
    monkeypatch.setattr(resolution, "checkout_for_project", lambda *_: checkout)

    record = _run(hc_pending_migrations, control)

    assert record.result == "FAIL"
    assert "0001_external" in record.detail


def test_external_project_passes_only_when_its_own_ledger_is_level(
    tmp_path: Path, monkeypatch,
) -> None:
    control = _control(_capability())
    checkout = _checkout(tmp_path)
    db = sqlite3.connect(checkout / "app/data/app.db")
    db.execute("INSERT INTO schema_version VALUES ('0001_external', '2.0.0')")
    db.commit()
    db.close()
    monkeypatch.setattr(resolution, "checkout_for_project", lambda *_: checkout)

    assert _run(hc_pending_migrations, control).result == "PASS"
    assert _run(hc_project_migration_ledger_contract, control).result == "PASS"


def test_external_three_digit_permanent_history_is_discovered(
    tmp_path: Path, monkeypatch,
) -> None:
    control = _control(_capability())
    checkout = _checkout(tmp_path, entry_name="001_external")
    db = sqlite3.connect(checkout / "app/data/app.db")
    db.execute("INSERT INTO schema_version VALUES ('001_external', '2.0.0')")
    db.commit()
    db.close()
    monkeypatch.setattr(resolution, "checkout_for_project", lambda *_: checkout)

    assert _run(hc_pending_migrations, control).result == "PASS"
    assert _run(hc_project_migration_ledger_contract, control).result == "PASS"


def test_missing_ledger_declaration_is_a_configuration_failure(
    tmp_path: Path, monkeypatch,
) -> None:
    control = _control(_capability(ledger=False))
    checkout = _checkout(tmp_path)
    monkeypatch.setattr(resolution, "checkout_for_project", lambda *_: checkout)

    record = _run(hc_pending_migrations, control)

    assert record.result == "FAIL"
    assert "ledger is required" in record.detail


def test_declared_floor_missing_from_applied_row_fails_contract(
    tmp_path: Path, monkeypatch,
) -> None:
    control = _control(_capability())
    checkout = _checkout(tmp_path)
    db = sqlite3.connect(checkout / "app/data/app.db")
    db.execute("INSERT INTO schema_version VALUES ('0001_external', NULL)")
    db.commit()
    db.close()
    monkeypatch.setattr(resolution, "checkout_for_project", lambda *_: checkout)

    record = _run(hc_project_migration_ledger_contract, control)

    assert record.result == "FAIL"
    assert "declared floors absent" in record.detail


def test_rollback_membership_passes_but_floor_evidence_is_limited_without_version(
    tmp_path: Path, monkeypatch,
) -> None:
    control = _control(_capability())
    checkout = _checkout(tmp_path)
    db = sqlite3.connect(checkout / "app/data/app.db")
    db.executemany(
        "INSERT INTO schema_version VALUES (?, ?)",
        [("0001_external", "2.0.0"), ("0002_newer", "3.0.0")],
    )
    db.commit()
    db.close()
    monkeypatch.setattr(resolution, "checkout_for_project", lambda *_: checkout)

    assert _run(hc_pending_migrations, control).result == "PASS"
    contract = _run(hc_project_migration_ledger_contract, control)
    assert contract.result == "WARN"
    assert "rollback-compatible" in contract.detail
    assert "artifact_version_env_var" in contract.detail


def test_rollback_floor_refuses_an_older_declared_artifact(
    tmp_path: Path, monkeypatch,
) -> None:
    control = _control(_capability(artifact_version_env_var="APP_VERSION"))
    checkout = _checkout(tmp_path)
    db = sqlite3.connect(checkout / "app/data/app.db")
    db.executemany(
        "INSERT INTO schema_version VALUES (?, ?)",
        [("0001_external", "2.0.0"), ("0002_newer", "3.0.0")],
    )
    db.commit()
    db.close()
    monkeypatch.setenv("APP_VERSION", "2.5.0")
    monkeypatch.setattr(resolution, "checkout_for_project", lambda *_: checkout)

    contract = _run(hc_project_migration_ledger_contract, control)
    assert contract.result == "FAIL"
    assert "0002_newer requires 3.0.0" in contract.detail


def test_rollback_floor_accepts_a_compatible_declared_artifact(
    tmp_path: Path, monkeypatch,
) -> None:
    control = _control(_capability(artifact_version_env_var="APP_VERSION"))
    checkout = _checkout(tmp_path)
    db = sqlite3.connect(checkout / "app/data/app.db")
    db.executemany(
        "INSERT INTO schema_version VALUES (?, ?)",
        [("0001_external", "2.0.0"), ("0002_newer", "3.0.0")],
    )
    db.commit()
    db.close()
    monkeypatch.setenv("APP_VERSION", "3.0.0")
    monkeypatch.setattr(resolution, "checkout_for_project", lambda *_: checkout)

    contract = _run(hc_project_migration_ledger_contract, control)
    assert contract.result == "PASS"
    assert "rollback floor checked" in contract.detail
