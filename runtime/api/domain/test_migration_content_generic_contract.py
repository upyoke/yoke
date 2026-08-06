"""The migration kernel follows caller-declared ledger/evidence identifiers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from runtime.api.domain.migration_artifact_trust_test_helpers import (
    artifact_verifier_for,
)
from yoke_core.domain.migration_audit_schema import (
    ensure_migration_audit_table,
    ensure_migration_ledger_table,
)
from yoke_core.domain.migration_boot_apply import apply_pending
from yoke_core.domain.migration_content_adoption import (
    MigrationContentAdoptionError,
    adopt_legacy_content_identities,
    verify_legacy_content_adoption,
)
from yoke_core.domain.migration_content_schema import (
    AdoptionEvidenceContract,
    adoption_evidence_verifier,
    adoption_evidence_writer,
)
from yoke_core.domain.migration_history import ordered_entries
from yoke_core.domain.migration_history_manifest import (
    ArtifactIdentity,
    manifest_from_history,
)
from yoke_core.domain.migration_ledger_contract import LedgerContract
import pytest


SOURCE_COMMIT = "e" * 40
RESTORE_POINT = "snapshot:custom-ledger"


def test_custom_ledger_schema_adoption_and_apply_use_no_fixed_identifiers(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE project_marks (label TEXT)")
    ensure_migration_audit_table(conn)
    ledger = LedgerContract(
        table="project_history",
        entry_column="entry_id",
        digest_column="body_hash",
        serving_floor_column="engine_floor",
        applied_at_column="recorded_on",
        applied_by_column="recorded_by",
    )
    evidence = AdoptionEvidenceContract(
        table="project_history_adoptions",
        entry_column="entry_id",
        content_digest_column="body_hash",
        engine_version_column="engine_release",
        source_artifact_column="artifact_name",
        source_digest_column="artifact_hash",
        source_commit_column="commit_id",
        manifest_digest_column="manifest_hash",
        actor_column="adopted_actor",
        timestamp_column="adopted_on",
    )
    conn.execute(
        "CREATE TABLE project_history ("
        "entry_id TEXT PRIMARY KEY, recorded_on TEXT NOT NULL, "
        "recorded_by TEXT, engine_floor TEXT)"
    )
    # The caller's additive convergence must precede a boot kernel that reads
    # the declared digest. This is the legacy custom-ledger rollout shape.
    ensure_migration_ledger_table(conn, ledger, evidence)
    (tmp_path / "0001_existing.py").write_text(
        "def apply(conn):\n    pass\n\n"
        "def invariants(conn):\n"
        '    row = conn.execute("SELECT body_hash FROM project_history '
        "WHERE entry_id='0001_existing'\").fetchone()\n"
        "    assert row == (None,)\n",
        encoding="utf-8",
    )
    (tmp_path / "0002_pending.py").write_text(
        "def apply(conn):\n"
        '    conn.execute("INSERT INTO project_marks VALUES '
        "('0002_pending')\")\n\n"
        "def invariants(conn):\n"
        '    assert conn.execute("SELECT count(*) FROM project_marks")'
        ".fetchone()[0] == 1\n",
        encoding="utf-8",
    )
    history = ordered_entries(tmp_path)
    conn.execute(
        "INSERT INTO project_history "
        "(entry_id, recorded_on, recorded_by, engine_floor, body_hash) "
        "VALUES ('0001_existing', 'now', 'legacy', NULL, NULL)"
    )
    conn.commit()
    artifact = ArtifactIdentity(
        "2.0.0",
        "project-engine.whl",
        "a" * 64,
        SOURCE_COMMIT,
    )
    manifest = manifest_from_history(history, artifact)

    adopted = adopt_legacy_content_identities(
        conn,
        history=history,
        ledger=ledger,
        manifest=manifest,
        artifact=artifact,
        expected_manifest_sha256=manifest.content_sha256,
        artifact_verifier=artifact_verifier_for(manifest),
        adopted_by="operator:test",
        write_evidence=adoption_evidence_writer(evidence),
        verify_evidence_immutability=adoption_evidence_verifier(ledger, evidence),
        entry_names=("0001_existing",),
    )
    outcome = apply_pending(
        conn,
        history=history,
        ledger=ledger,
        applied_by="boot",
        running_version="",
        external_restore_point=RESTORE_POINT,
    )

    assert tuple(record.entry_name for record in adopted) == ("0001_existing",)
    assert outcome.applied == ("0002_pending",)
    rows = conn.execute(
        "SELECT entry_id, body_hash FROM project_history ORDER BY entry_id"
    ).fetchall()
    assert rows == [
        ("0001_existing", history[0].content_sha256),
        ("0002_pending", history[1].content_sha256),
    ]
    evidence_row = conn.execute(
        "SELECT entry_id, commit_id, manifest_hash FROM project_history_adoptions"
    ).fetchone()
    assert evidence_row == (
        "0001_existing",
        SOURCE_COMMIT,
        manifest.content_sha256,
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type='table' AND name='applied_migrations'"
        ).fetchone()[0]
        == 0
    )


def _apply_only_adoption_case(tmp_path: Path):
    conn = sqlite3.connect(":memory:")
    ledger = LedgerContract(
        table="project_history",
        entry_column="entry_id",
        digest_column="body_hash",
        serving_floor_column="engine_floor",
    )
    evidence = AdoptionEvidenceContract(table="project_history_adoptions")
    conn.execute(
        "CREATE TABLE project_history (entry_id TEXT PRIMARY KEY, "
        "engine_floor TEXT, body_hash TEXT)"
    )
    ensure_migration_ledger_table(conn, ledger, evidence)
    for name in ("0001_first", "0002_second"):
        (tmp_path / f"{name}.py").write_text(
            "def apply(conn):\n    pass\n",
            encoding="utf-8",
        )
        conn.execute(
            "INSERT INTO project_history VALUES (?, NULL, NULL)",
            (name,),
        )
    conn.execute("CREATE TABLE verifier_marks (name TEXT)")
    conn.commit()
    history = ordered_entries(tmp_path)
    artifact = ArtifactIdentity("2.0.0", "project.whl", "a" * 64, SOURCE_COMMIT)
    return (
        conn,
        ledger,
        evidence,
        history,
        artifact,
        manifest_from_history(history, artifact),
    )


def test_apply_only_history_uses_project_owned_verifier_registry(
    tmp_path: Path,
) -> None:
    conn, ledger, evidence, history, artifact, manifest = _apply_only_adoption_case(
        tmp_path
    )

    records = adopt_legacy_content_identities(
        conn,
        history=history,
        ledger=ledger,
        manifest=manifest,
        artifact=artifact,
        expected_manifest_sha256=manifest.content_sha256,
        artifact_verifier=artifact_verifier_for(manifest),
        adopted_by="operator:test",
        write_evidence=adoption_evidence_writer(evidence),
        verify_evidence_immutability=adoption_evidence_verifier(ledger, evidence),
        entry_names=("0001_first",),
        state_verifiers={
            "0001_first": lambda database: database.execute("SELECT 1").fetchone()
        },
    )

    assert tuple(record.entry_name for record in records) == ("0001_first",)


@pytest.mark.parametrize(
    "state_verifiers",
    [
        {},
        {"0001_first": "not-callable"},
        lambda _entry: None,
    ],
)
def test_unknown_or_noncallable_project_verifier_refuses(
    tmp_path: Path,
    state_verifiers,
) -> None:
    conn, ledger, _evidence, history, artifact, manifest = _apply_only_adoption_case(
        tmp_path
    )

    with pytest.raises(MigrationContentAdoptionError, match="no callable declared"):
        verify_legacy_content_adoption(
            conn,
            history=history,
            ledger=ledger,
            manifest=manifest,
            artifact=artifact,
            expected_manifest_sha256=manifest.content_sha256,
            artifact_verifier=artifact_verifier_for(manifest),
            entry_names=("0001_first",),
            state_verifiers=state_verifiers,
        )

    assert conn.execute(
        "SELECT body_hash FROM project_history WHERE entry_id='0001_first'"
    ).fetchone() == (None,)


def test_project_verifier_failure_rolls_back_all_savepoint_writes(
    tmp_path: Path,
) -> None:
    conn, ledger, _evidence, history, artifact, manifest = _apply_only_adoption_case(
        tmp_path
    )

    def resolve(entry):
        if entry.name == "0001_first":
            return lambda database: database.execute(
                "INSERT INTO verifier_marks VALUES ('temporary')"
            )

        def fail(_database):
            raise AssertionError("state differs")

        return fail

    with pytest.raises(MigrationContentAdoptionError, match="state differs"):
        verify_legacy_content_adoption(
            conn,
            history=history,
            ledger=ledger,
            manifest=manifest,
            artifact=artifact,
            expected_manifest_sha256=manifest.content_sha256,
            artifact_verifier=artifact_verifier_for(manifest),
            state_verifiers=resolve,
        )

    assert conn.execute("SELECT count(*) FROM verifier_marks").fetchone() == (0,)


@pytest.mark.parametrize("verification_case", ["missing", "mismatched"])
def test_artifact_verification_refuses_before_connection_access(
    tmp_path: Path,
    verification_case: str,
) -> None:
    conn, ledger, _evidence, history, artifact, manifest = _apply_only_adoption_case(
        tmp_path
    )
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    verifier = (
        None
        if verification_case == "missing"
        else artifact_verifier_for(manifest, manifest_sha256="f" * 64)
    )

    with pytest.raises(MigrationContentAdoptionError, match="artifact verification"):
        verify_legacy_content_adoption(
            conn,
            history=history,
            ledger=ledger,
            manifest=manifest,
            artifact=artifact,
            expected_manifest_sha256=manifest.content_sha256,
            artifact_verifier=verifier,
        )

    assert statements == []
