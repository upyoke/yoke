"""Verify or adopt legacy Yoke migration digests on an admin connection.

This is the installed, sanctioned direct-authority surface for fleet adoption.
It consumes an exact ``yoke-core`` wheel plus its release manifest and record,
then verifies all three GitHub attestations against the explicitly supplied
repository and source commit. The safe receipt is printed before any database
operation; the manifest digest is recorded with every adoption row.

Examples::

    python3 -m yoke_core.tools.adopt_migration_content_identity \
      stage-db-admin --wheel yoke_core.whl --manifest migration-history.json \
      --release-evidence migration-history-record.json \
      --repository upyoke/yoke --source-commit <full-commit> \
      --manifest-sha256 <sha256> \
      --adopted-by operator:<name> --prepare

    python3 -m yoke_core.tools.adopt_migration_content_identity \
      prod-db-admin yoke_acme --wheel yoke_core.whl \
      --manifest migration-history.json --source-commit <full-commit> \
      --release-evidence migration-history-record.json \
      --repository upyoke/yoke --manifest-sha256 <sha256> \
      --adopted-by operator:<name> --apply

``--prepare`` is the separately committed pre-deploy phase: it adds the
nullable digest column, evidence table, and immutability guards while old code
is still serving.  A later invocation without a mode runs every selected entry
invariant and prints the adoption plan without changing the ledger.  ``--apply``
performs that verification again and atomically adopts the selected rows.  With
no database operands the command targets every tenant database selected from
the environment's Platform catalog.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

from yoke_core.domain.migration_artifact_trust import (
    MIGRATION_MANIFEST_ROLE,
    SOURCE_ARTIFACT_ROLE,
    ArtifactVerifier,
    artifact_verification_request,
)
from yoke_core.domain.migration_content_adoption import (
    MigrationContentAdoptionError,
    verify_legacy_content_adoption,
)
from yoke_core.domain.migration_history_manifest import (
    MigrationHistoryManifest,
    MigrationHistoryManifestError,
    load_manifest,
)
from yoke_core.domain.migration_yoke_ledger import (
    YOKE_LEDGER_CONTRACT,
    YOKE_RELEASE_ATTESTATION_WORKFLOW,
    adopt_yoke_legacy_content_identities,
    prepare_yoke_migration_content_schema,
    yoke_migration_content_schema_is_prepared,
)
from yoke_core.tools.github_artifact_attestation import (
    GitHubArtifactAttestationVerifier,
    GitHubAttestationSubject,
)
from yoke_core.tools.migration_history_release_artifact import (
    manifest_for_core_wheel_path,
    materialize_core_wheel_history,
    validate_release_evidence,
)


YOKE_RELEASE_RECORD_ROLE = "release_record"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adopt-migration-content-identity",
        description=(
            "Verify or adopt legacy NULL migration digests from one attested "
            "Yoke release artifact."
        ),
    )
    parser.add_argument(
        "environment",
        help="Configured admin connection, such as stage-db-admin or prod-db-admin.",
    )
    parser.add_argument(
        "databases", nargs="*", help="Tenant DB names; defaults to the full fleet."
    )
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--release-evidence", type=Path, required=True)
    parser.add_argument(
        "--repository",
        required=True,
        help="GitHub owner/repository whose release workflow signed the artifacts.",
    )
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--adopted-by", required=True)
    parser.add_argument(
        "--entry",
        action="append",
        dest="entries",
        default=[],
        help="Adopt one named entry; repeat for a deliberate partial adoption.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--prepare",
        action="store_true",
        help=(
            "Commit additive nullable schema as a separate pre-deploy phase; "
            "does not verify or adopt rows."
        ),
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Commit adoption. Omit to verify state equivalence and print the plan.",
    )
    return parser


def _selected_manifest(
    *,
    wheel: Path,
    manifest_path: Path,
    release_evidence_path: Path,
    source_commit: str,
    manifest_sha256: str,
) -> MigrationHistoryManifest:
    expected = manifest_for_core_wheel_path(
        wheel,
        source_commit=source_commit,
    )
    loaded = load_manifest(
        manifest_path,
        expected_artifact=expected.artifact,
        expected_manifest_sha256=manifest_sha256,
    )
    if loaded != expected:
        raise MigrationHistoryManifestError(
            "selected manifest entries do not match the exact core wheel"
        )
    validate_release_evidence(
        release_evidence_path,
        loaded,
        expected_source_commit=source_commit,
        expected_manifest_sha256=manifest_sha256,
    )
    return loaded


def _admin_authority_dsn(environment: str) -> str:
    """Resolve exactly one operator-selected local Postgres authority."""
    from yoke_contracts.machine_config.schema import DB_ADMIN_ENV_SUFFIX
    from yoke_core.domain import db_backend, yoke_connected_env

    selected = environment.strip()
    if not selected.endswith(DB_ADMIN_ENV_SUFFIX):
        raise MigrationContentAdoptionError(
            "migration adoption requires an explicitly selected *-db-admin connection"
        )
    os.environ["YOKE_ENV"] = selected
    try:
        active = yoke_connected_env.load_active()
        if active is None or active.environment != selected:
            raise MigrationContentAdoptionError(
                f"admin connection {selected!r} is not configured"
            )
        if active.backend != db_backend.POSTGRES:
            raise MigrationContentAdoptionError(
                f"admin connection {selected!r} is not local Postgres"
            )
        return yoke_connected_env.resolve_postgres_dsn(
            dsn_env=db_backend.PG_DSN_ENV,
            dsn_file_env=db_backend.PG_DSN_FILE_ENV,
        ).dsn
    except yoke_connected_env.ConnectedEnvError as exc:
        raise MigrationContentAdoptionError(
            f"admin connection {selected!r} could not be resolved: {exc}"
        ) from exc


def _database_dsn(authority_dsn: str, database: str) -> str:
    from yoke_core.tools.yoke_migration_fleet import database_dsn

    return database_dsn(authority_dsn, database)


def _database_names(requested: Sequence[str], *, authority_dsn: str) -> tuple[str, ...]:
    if requested:
        return tuple(requested)
    from yoke_core.tools.yoke_migration_fleet import tenant_databases

    return tuple(
        tenant_databases(lambda database: _database_dsn(authority_dsn, database))
    )


def _connect_database(database: str, *, authority_dsn: str) -> Any:
    from yoke_core.domain import db_backend

    return db_backend.connect_psycopg(
        _database_dsn(authority_dsn, database),
    )


def _run_database(
    database: str,
    *,
    history: Sequence[Any],
    manifest: MigrationHistoryManifest,
    expected_manifest_sha256: str,
    adopted_by: str,
    entry_names: Sequence[str] | None,
    mode: str,
    artifact_verifier: ArtifactVerifier,
    authority_dsn: str,
) -> tuple[str, ...]:
    with _connect_database(database, authority_dsn=authority_dsn) as conn:
        if mode == "PREPARE":
            prepare_yoke_migration_content_schema(conn)
            return ()
        if not yoke_migration_content_schema_is_prepared(conn):
            raise MigrationContentAdoptionError(
                "migration content schema is not prepared; run this command "
                "with --prepare and deploy only after that phase commits"
            )
        if mode == "APPLY":
            records = adopt_yoke_legacy_content_identities(
                conn,
                history=history,
                manifest=manifest,
                artifact=manifest.artifact,
                expected_manifest_sha256=expected_manifest_sha256,
                artifact_verifier=artifact_verifier,
                adopted_by=adopted_by,
                entry_names=entry_names,
            )
            return tuple(record.entry_name for record in records)
        selected = verify_legacy_content_adoption(
            conn,
            history=history,
            ledger=YOKE_LEDGER_CONTRACT,
            manifest=manifest,
            artifact=manifest.artifact,
            expected_manifest_sha256=expected_manifest_sha256,
            artifact_verifier=artifact_verifier,
            entry_names=entry_names,
        )
        conn.rollback()
        return selected


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        manifest = _selected_manifest(
            wheel=args.wheel,
            manifest_path=args.manifest,
            release_evidence_path=args.release_evidence,
            source_commit=args.source_commit,
            manifest_sha256=args.manifest_sha256,
        )
        artifact_verifier = GitHubArtifactAttestationVerifier(
            repository=args.repository,
            source_commit=args.source_commit,
            signer_workflow=(f"{args.repository}/{YOKE_RELEASE_ATTESTATION_WORKFLOW}"),
            subjects=(
                GitHubAttestationSubject(SOURCE_ARTIFACT_ROLE, args.wheel),
                GitHubAttestationSubject(MIGRATION_MANIFEST_ROLE, args.manifest),
                GitHubAttestationSubject(
                    YOKE_RELEASE_RECORD_ROLE,
                    args.release_evidence,
                ),
            ),
        )
        verification_receipt = artifact_verifier(
            artifact_verification_request(manifest)
        )
        print(f"environment: {args.environment}")
        print(f"artifact source commit: {manifest.artifact.source_commit}")
        print(f"manifest sha256: {manifest.content_sha256}")
        print(
            "artifact verification receipt: "
            + json.dumps(
                verification_receipt.to_json(),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        authority_dsn = _admin_authority_dsn(args.environment)
        databases = _database_names(args.databases, authority_dsn=authority_dsn)
        if not databases:
            raise MigrationContentAdoptionError(
                "selected environment has no tenant databases"
            )
        entries = tuple(args.entries) or None
        mode = "PREPARE" if args.prepare else ("APPLY" if args.apply else "VERIFY")
        with tempfile.TemporaryDirectory(prefix="yoke-migration-history-") as work:
            history = materialize_core_wheel_history(
                args.wheel,
                Path(work) / "migrations",
            )
            for database in databases:
                selected = _run_database(
                    database,
                    history=history,
                    manifest=manifest,
                    expected_manifest_sha256=args.manifest_sha256,
                    adopted_by=args.adopted_by,
                    entry_names=entries,
                    mode=mode,
                    artifact_verifier=artifact_verifier,
                    authority_dsn=authority_dsn,
                )
                if mode == "PREPARE":
                    print(
                        f"PREPARE {database}: additive digest/evidence schema committed"
                    )
                else:
                    print(f"{mode} {database}: {list(selected)}")
        return 0
    except (
        OSError,
        ValueError,
        MigrationContentAdoptionError,
        MigrationHistoryManifestError,
    ) as exc:
        print(f"adopt-migration-content-identity: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
