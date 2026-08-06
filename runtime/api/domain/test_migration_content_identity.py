"""Focused migration content-identity, adoption, and rollback fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.migration_artifact_trust_test_helpers import (
    artifact_verifier_for,
)
from runtime.api.domain.migration_boot_test_helpers import (
    RESTORE_POINT,
    apply_pending,
    connection as _connection,
    history as _history,
    marks as _marks,
    stamp_history,
)
from yoke_core.domain.migration_content_adoption import (
    MigrationContentAdoptionError,
)
from yoke_core.domain.migration_content_identity import (
    MigrationContentMismatch,
    read_content_identity_status,
)
from yoke_core.domain.migration_history_manifest import (
    ArtifactIdentity,
    MigrationHistoryManifestError,
    load_manifest,
    manifest_from_history,
    write_manifest,
)
from yoke_core.domain.migration_history import ordered_entries
from yoke_core.domain.migration_ledger_contract import LedgerContract
from yoke_core.domain.migration_yoke_ledger import (
    YOKE_ADOPTION_EVIDENCE_TABLE,
    YOKE_LEDGER_CONTRACT,
    adopt_yoke_legacy_content_identities,
)

SOURCE_COMMIT = "c" * 40


def _adoptable_history(
    tmp_path: Path,
    *names: str,
    failing_invariant: str | None = None,
):
    for name in names:
        invariant = (
            "    raise AssertionError('state differs')\n"
            if name == failing_invariant
            else (
                '    row = conn.execute("SELECT content_sha256 FROM '
                'applied_migrations WHERE migration_name = ?", '
                f"('{name}',)).fetchone()\n"
                "    assert row[0] is None, 'digest changed before invariant'\n"
            )
        )
        (tmp_path / f"{name}.py").write_text(
            "def apply(conn):\n    pass\n\ndef invariants(conn):\n" + invariant,
            encoding="utf-8",
        )
    return ordered_entries(tmp_path)


def test_new_apply_atomically_records_raw_digest(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first", "0002_second")

    outcome = apply_pending(
        conn,
        history=history,
        applied_by="test",
        running_version="",
        external_restore_point=RESTORE_POINT,
    )

    rows = conn.execute(
        "SELECT migration_name, content_sha256 FROM applied_migrations "
        "ORDER BY migration_name"
    ).fetchall()
    assert outcome.applied == ("0001_first", "0002_second")
    assert rows == [(entry.name, entry.content_sha256) for entry in history]


def test_fresh_stamp_records_every_digest_without_running_entries(
    tmp_path: Path,
) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first", "0002_second")

    stamp_history(conn, history, applied_by="birth")

    rows = conn.execute(
        "SELECT migration_name, content_sha256 FROM applied_migrations "
        "ORDER BY migration_name"
    ).fetchall()
    assert rows == [(entry.name, entry.content_sha256) for entry in history]
    assert _marks(conn) == []


def test_legacy_null_is_adoption_required_but_does_not_brick_boot(
    tmp_path: Path,
) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first")
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by, content_sha256) "
        "VALUES ('0001_first', 'now', 'legacy', NULL)"
    )

    status = read_content_identity_status(conn, history, YOKE_LEDGER_CONTRACT)
    outcome = apply_pending(
        conn, history=history, applied_by="test", running_version=""
    )

    assert status.adoption_required == ("0001_first",)
    assert status.adoptable == ("0001_first",)
    assert outcome.applied == ()


def test_mismatch_refuses_before_restore_or_mutation(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first", "0002_second")
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by, content_sha256) "
        "VALUES ('0001_first', 'now', 'test', ?)",
        ("0" * 64,),
    )

    with pytest.raises(MigrationContentMismatch, match="0001_first"):
        apply_pending(conn, history=history, applied_by="test", running_version="")

    assert _marks(conn) == []
    assert conn.execute("SELECT count(*) FROM applied_migrations").fetchone()[0] == 1


def test_ledger_ahead_remains_a_valid_rollback_shape(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first")
    conn.executemany(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by, content_sha256) "
        "VALUES (?, 'now', 'test', ?)",
        [
            ("0001_first", history[0].content_sha256),
            ("0002_from_newer_artifact", "f" * 64),
        ],
    )

    status = read_content_identity_status(conn, history, YOKE_LEDGER_CONTRACT)
    outcome = apply_pending(
        conn, history=history, applied_by="test", running_version=""
    )

    assert status.ledger_ahead == ("0002_from_newer_artifact",)
    assert status.mismatches == ()
    assert outcome.applied == ()


def test_generic_comparison_uses_declared_project_ledger(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first")
    conn.execute(
        "CREATE TABLE project_history (entry_id TEXT PRIMARY KEY, digest TEXT, "
        "floor TEXT)"
    )
    conn.execute(
        "INSERT INTO project_history VALUES ('0001_first', ?, NULL)",
        (history[0].content_sha256,),
    )
    ledger = LedgerContract(
        table="project_history",
        entry_column="entry_id",
        digest_column="digest",
        serving_floor_column="floor",
    )

    status = read_content_identity_status(conn, history, ledger)

    assert status.verified == ("0001_first",)


def test_manifest_loading_is_pinned_to_selected_artifact(tmp_path: Path) -> None:
    history = _history(tmp_path, "0001_first")
    artifact = ArtifactIdentity(
        "1.2.3",
        "core.whl",
        "a" * 64,
        SOURCE_COMMIT,
    )
    manifest = manifest_from_history(history, artifact)
    path = tmp_path / "migration-history.json"
    write_manifest(path, manifest)

    assert load_manifest(path, expected_artifact=artifact) == manifest
    with pytest.raises(MigrationHistoryManifestError, match="does not match"):
        load_manifest(
            path,
            expected_artifact=ArtifactIdentity(
                "1.2.3",
                "core.whl",
                "b" * 64,
                SOURCE_COMMIT,
            ),
        )


def test_partial_adoption_updates_only_null_and_appends_evidence(
    tmp_path: Path,
) -> None:
    conn = _connection()
    history = _adoptable_history(tmp_path, "0001_first", "0002_second")
    conn.executemany(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by, content_sha256) "
        "VALUES (?, 'now', 'legacy', NULL)",
        [(entry.name,) for entry in history],
    )
    artifact = ArtifactIdentity(
        "1.2.3",
        "yoke_core-1.2.3.whl",
        "a" * 64,
        SOURCE_COMMIT,
    )
    manifest = manifest_from_history(history, artifact)

    records = adopt_yoke_legacy_content_identities(
        conn,
        history=history,
        manifest=manifest,
        artifact=artifact,
        expected_manifest_sha256=manifest.content_sha256,
        artifact_verifier=artifact_verifier_for(manifest),
        adopted_by="operator:test",
        entry_names=("0001_first",),
        adopted_at="2026-08-06T00:00:00Z",
    )

    assert tuple(record.entry_name for record in records) == ("0001_first",)
    ledger = conn.execute(
        "SELECT migration_name, content_sha256 FROM applied_migrations "
        "ORDER BY migration_name"
    ).fetchall()
    assert ledger == [
        ("0001_first", history[0].content_sha256),
        ("0002_second", None),
    ]
    evidence = conn.execute(
        f"SELECT migration_name, source_artifact, source_commit, "
        f"manifest_sha256, adopted_by FROM "
        f"{YOKE_ADOPTION_EVIDENCE_TABLE}"
    ).fetchall()
    assert evidence == [
        (
            "0001_first",
            "yoke_core-1.2.3.whl",
            SOURCE_COMMIT,
            manifest.content_sha256,
            "operator:test",
        )
    ]

    with pytest.raises(MigrationContentAdoptionError, match="currently NULL"):
        adopt_yoke_legacy_content_identities(
            conn,
            history=history,
            manifest=manifest,
            artifact=artifact,
            expected_manifest_sha256=manifest.content_sha256,
            artifact_verifier=artifact_verifier_for(manifest),
            adopted_by="operator:test",
            entry_names=("0001_first",),
        )
    assert (
        conn.execute(f"SELECT count(*) FROM {YOKE_ADOPTION_EVIDENCE_TABLE}").fetchone()[
            0
        ]
        == 1
    )


def test_invariant_failure_leaves_digest_and_evidence_unchanged(
    tmp_path: Path,
) -> None:
    conn = _connection()
    history = _adoptable_history(
        tmp_path,
        "0001_first",
        failing_invariant="0001_first",
    )
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by, content_sha256) "
        "VALUES ('0001_first', 'now', 'legacy', NULL)"
    )
    conn.commit()
    artifact = ArtifactIdentity(
        "1.2.3",
        "yoke_core-1.2.3.whl",
        "a" * 64,
        SOURCE_COMMIT,
    )
    manifest = manifest_from_history(history, artifact)

    with pytest.raises(MigrationContentAdoptionError, match="state differs"):
        adopt_yoke_legacy_content_identities(
            conn,
            history=history,
            manifest=manifest,
            artifact=artifact,
            expected_manifest_sha256=manifest.content_sha256,
            artifact_verifier=artifact_verifier_for(manifest),
            adopted_by="operator:test",
        )

    assert (
        conn.execute("SELECT content_sha256 FROM applied_migrations").fetchone()[0]
        is None
    )
    assert (
        conn.execute(f"SELECT count(*) FROM {YOKE_ADOPTION_EVIDENCE_TABLE}").fetchone()[
            0
        ]
        == 0
    )
