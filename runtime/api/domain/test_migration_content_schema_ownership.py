"""Admin preparation preserves serving-role migration convergence."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from runtime.api.domain.migration_artifact_trust_test_helpers import (
    artifact_verifier_for,
)
from runtime.api.domain.migration_content_owner_test_helpers import (
    authority_case,
    select_schema,
)
from yoke_core.domain import migration_fleet_ownership
from yoke_core.domain.migration_content_adoption import (
    adopt_legacy_content_identities,
)
from yoke_core.domain.migration_content_schema import (
    AdoptionEvidenceContract,
    adoption_evidence_verifier,
    adoption_evidence_writer,
    converge_migration_content_schema,
    migration_content_schema_is_prepared,
    prepare_migration_content_schema,
)
from yoke_core.domain.migration_content_schema_ownership import (
    MigrationContentSchemaOwnershipError,
    migration_content_guard_function_names,
    migration_content_schema_owner_is_aligned,
)
from yoke_core.domain.migration_history import ordered_entries
from yoke_core.domain.migration_history_manifest import (
    ArtifactIdentity,
    manifest_from_history,
)
from yoke_core.domain.migration_ledger_contract import LedgerContract
from yoke_core.domain.migration_yoke_ledger import (
    YOKE_ADOPTION_EVIDENCE_CONTRACT,
    YOKE_LEDGER_CONTRACT,
    adopt_yoke_legacy_content_identities,
    prepare_yoke_migration_content_schema,
)


LEDGER = LedgerContract(
    table="tenant_history",
    entry_column="entry_id",
    digest_column="body_hash",
    serving_floor_column="engine_floor",
)
EVIDENCE = AdoptionEvidenceContract(table="tenant_history_adoptions")
SOURCE_COMMIT = "e" * 40


def _create_legacy_ledger(
    conn: psycopg.Connection,
    ledger: LedgerContract,
) -> None:
    conn.execute(
        f"""
        CREATE TABLE {ledger.table} (
            {ledger.entry_column} TEXT PRIMARY KEY,
            {ledger.applied_at_column} TEXT NOT NULL,
            {ledger.applied_by_column} TEXT,
            {ledger.serving_floor_column} TEXT
        )
        """
    )
    conn.execute(
        f"INSERT INTO {ledger.table} "
        f"({ledger.entry_column}, {ledger.applied_at_column}, "
        f"{ledger.applied_by_column}, {ledger.serving_floor_column}) "
        "VALUES ('0001_existing', 'now', 'legacy', NULL)"
    )
    conn.commit()


def _guard_function_owners(
    conn: psycopg.Connection,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT pg_get_userbyid(procedure.proowner) "
        "FROM pg_trigger AS trigger "
        "JOIN pg_proc AS procedure ON procedure.oid=trigger.tgfoid "
        "WHERE trigger.tgrelid IN (to_regclass(%s), to_regclass(%s)) "
        "AND NOT trigger.tgisinternal",
        (ledger.table, evidence.table),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _adoption_artifact(tmp_path: Path, ledger: LedgerContract):
    (tmp_path / "0001_existing.py").write_text(
        "def apply(conn):\n    pass\n\n"
        "def invariants(conn):\n"
        f'    row = conn.execute("SELECT {ledger.digest_column} FROM '
        f"{ledger.table} WHERE {ledger.entry_column}='0001_existing'\").fetchone()\n"
        "    assert row == (None,)\n",
        encoding="utf-8",
    )
    history = ordered_entries(tmp_path)
    artifact = ArtifactIdentity(
        "2.0.0",
        "project-engine.whl",
        "a" * 64,
        SOURCE_COMMIT,
    )
    return history, artifact, manifest_from_history(history, artifact)


def _prepare_and_adopt(
    admin: psycopg.Connection,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
    history,
    artifact: ArtifactIdentity,
    manifest,
    *,
    yoke_adapter: bool,
):
    if yoke_adapter:
        prepare_yoke_migration_content_schema(admin)
        return adopt_yoke_legacy_content_identities(
            admin,
            history=history,
            manifest=manifest,
            artifact=artifact,
            expected_manifest_sha256=manifest.content_sha256,
            artifact_verifier=artifact_verifier_for(manifest),
            adopted_by="operator:test",
        )
    prepare_migration_content_schema(admin, ledger, evidence)
    return adopt_legacy_content_identities(
        admin,
        history=history,
        ledger=ledger,
        manifest=manifest,
        artifact=artifact,
        expected_manifest_sha256=manifest.content_sha256,
        artifact_verifier=artifact_verifier_for(manifest),
        adopted_by="operator:test",
        write_evidence=adoption_evidence_writer(evidence),
        verify_evidence_immutability=adoption_evidence_verifier(ledger, evidence),
        transaction_authority=lambda: (
            migration_fleet_ownership.owner_transfer_authority(
                admin,
                owner=migration_fleet_ownership.table_owner(admin, ledger.table),
            )
        ),
    )


@pytest.mark.parametrize(
    "yoke_adapter", [False, True], ids=["generic", "installed-yoke"]
)
def test_admin_prepare_and_adopt_use_ledger_owner_when_database_owner_differs(
    cluster_role_authority,
    tmp_path: Path,
    yoke_adapter: bool,
) -> None:
    ledger = YOKE_LEDGER_CONTRACT if yoke_adapter else LEDGER
    evidence = YOKE_ADOPTION_EVIDENCE_CONTRACT if yoke_adapter else EVIDENCE
    with authority_case() as case:
        with psycopg.connect(case.tenant_dsn) as tenant:
            select_schema(tenant, case.schema)
            _create_legacy_ledger(tenant, ledger)
        history, artifact, manifest = _adoption_artifact(tmp_path, ledger)

        with psycopg.connect(case.admin_dsn) as admin:
            select_schema(admin, case.schema)
            assert admin.execute(
                "SELECT pg_has_role(current_user, %s, 'SET')",
                (case.tenant_role,),
            ).fetchone() == (False,)
            records = _prepare_and_adopt(
                admin,
                ledger,
                evidence,
                history,
                artifact,
                manifest,
                yoke_adapter=yoke_adapter,
            )

            evidence_owner = admin.execute(
                "SELECT tableowner FROM pg_tables WHERE schemaname=%s AND tablename=%s",
                (case.schema, evidence.table),
            ).fetchone()
            assert evidence_owner == (case.tenant_role,)
            assert _guard_function_owners(admin, ledger, evidence) == {case.tenant_role}
            assert migration_content_schema_owner_is_aligned(admin, ledger, evidence)
            assert tuple(record.entry_name for record in records) == ("0001_existing",)
            assert admin.execute(
                "SELECT pg_has_role(current_user, %s, 'SET')",
                (case.tenant_role,),
            ).fetchone() == (False,)

        with psycopg.connect(case.admin_dsn) as admin:
            assert admin.execute(
                "SELECT pg_has_role(current_user, %s, 'SET')",
                (case.tenant_role,),
            ).fetchone() == (False,)

        with psycopg.connect(case.tenant_dsn) as tenant:
            select_schema(tenant, case.schema)
            assert tenant.execute(
                f"SELECT {ledger.digest_column} FROM {ledger.table}"
            ).fetchone() == (history[0].content_sha256,)
            assert tenant.execute(
                f"SELECT count(*) FROM {evidence.table}"
            ).fetchone() == (1,)
            converge_migration_content_schema(
                tenant,
                ledger,
                evidence,
                repair_existing_guards=True,
            )
            assert migration_content_schema_is_prepared(tenant, ledger, evidence)


def test_failed_prepare_rolls_back_schema_and_temporary_owner_authority(
    cluster_role_authority,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with authority_case() as case:
        with psycopg.connect(case.tenant_dsn) as tenant:
            select_schema(tenant, case.schema)
            _create_legacy_ledger(tenant, LEDGER)

        monkeypatch.setattr(
            migration_fleet_ownership,
            "schema_objects_owned_by",
            lambda *_args, **_kwargs: False,
        )
        with psycopg.connect(case.admin_dsn) as admin:
            select_schema(admin, case.schema)
            with pytest.raises(
                MigrationContentSchemaOwnershipError,
                match="not owned",
            ):
                prepare_migration_content_schema(admin, LEDGER, EVIDENCE)

            assert admin.execute(
                "SELECT pg_has_role(current_user, %s, 'SET')",
                (case.tenant_role,),
            ).fetchone() == (False,)
            assert (
                admin.execute(
                    "SELECT 1 FROM pg_attribute "
                    "WHERE attrelid=to_regclass(%s) AND attname=%s "
                    "AND NOT attisdropped",
                    (
                        f"{case.schema}.{LEDGER.table}",
                        LEDGER.digest_column,
                    ),
                ).fetchone()
                is None
            )
            assert admin.execute(
                "SELECT to_regclass(%s)",
                (f"{case.schema}.{EVIDENCE.table}",),
            ).fetchone() == (None,)
            functions = migration_content_guard_function_names(LEDGER, EVIDENCE)
            assert admin.execute(
                "SELECT count(*) FROM pg_proc AS procedure "
                "JOIN pg_namespace AS namespace "
                "ON namespace.oid=procedure.pronamespace "
                "WHERE namespace.nspname=%s AND procedure.proname=ANY(%s)",
                (case.schema, list(functions)),
            ).fetchone() == (0,)
