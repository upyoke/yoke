"""Atomic, artifact-bound adoption of legacy NULL migration digests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any, Callable, Sequence, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.migration_apply_contract import MigrationApplyError
from yoke_core.domain.migration_content_identity import (
    SHA256_PATTERN,
    require_matching_content_identity,
)
from yoke_core.domain.migration_history import MigrationEntry
from yoke_core.domain.migration_history import load_migration_module
from yoke_core.domain.migration_history_manifest import (
    ArtifactIdentity,
    MigrationHistoryManifest,
)
from yoke_core.domain.migration_ledger_contract import LedgerContract


class MigrationContentAdoptionError(MigrationApplyError):
    """Explicit legacy adoption is unsafe or raced with another writer."""


@dataclass(frozen=True)
class AdoptionRecord:
    """Append-only evidence for one NULL-to-digest transition."""

    entry_name: str
    content_sha256: str
    artifact_engine_version: str
    source_artifact: str
    source_sha256: str
    source_commit: str
    manifest_sha256: str
    adopted_by: str
    adopted_at: str


EvidenceWriter = Callable[[Any, Tuple[AdoptionRecord, ...]], None]
EvidenceGuardVerifier = Callable[[Any], bool]
MigrationStateVerifier = Callable[[Any], None]
MigrationStateVerifierResolver = Callable[
    [MigrationEntry], MigrationStateVerifier | None
]
MigrationStateVerifierSource = (
    Mapping[str, MigrationStateVerifier] | MigrationStateVerifierResolver
)
_VERIFY_SAVEPOINT = "migration_content_identity_verify"


def verify_migration_entry_state_equivalence(
    conn: Any,
    entry: MigrationEntry,
    *,
    state_verifiers: MigrationStateVerifierSource | None = None,
) -> None:
    """Require a caller-declared verifier or packaged invariant to hold now.

    Adoption says an historical entry's exact bytes already describe this
    database.  Membership plus an artifact manifest cannot prove that claim;
    a project-owned verifier may prove apply-only histories. When none is
    supplied, the entry's own invariant remains the artifact-local fallback.
    """
    if state_verifiers is None:
        module = load_migration_module(entry.path, entry.name)
        verifier = getattr(module, "invariants", None)
        label = "packaged migration invariant"
        missing = "has no callable invariants(conn) state-equivalence verifier"
    else:
        label = "declared project migration state verifier"
        missing = "has no callable declared state-equivalence verifier"
        if isinstance(state_verifiers, Mapping):
            verifier = state_verifiers.get(entry.name)
        elif callable(state_verifiers):
            try:
                verifier = state_verifiers(entry)
            except KeyError:
                verifier = None
            except Exception as exc:
                raise MigrationContentAdoptionError(
                    f"{entry.name} state-verifier resolution failed: {exc}"
                ) from exc
        else:
            verifier = None
    if not callable(verifier):
        raise MigrationContentAdoptionError(
            f"{entry.name} {missing}; its legacy digest cannot be adopted"
        )
    try:
        verifier(conn)
    except Exception as exc:
        raise MigrationContentAdoptionError(
            f"{entry.name} does not satisfy its {label}: {exc}"
        ) from exc


def verify_legacy_content_adoption(
    conn: Any,
    *,
    history: Sequence[MigrationEntry],
    ledger: LedgerContract,
    manifest: MigrationHistoryManifest,
    artifact: ArtifactIdentity,
    expected_manifest_sha256: str,
    entry_names: Sequence[str] | None = None,
    state_verifiers: MigrationStateVerifierSource | None = None,
) -> Tuple[str, ...]:
    """Return adoptable names after artifact, digest, and state proof.

    Every selected invariant runs inside a savepoint that is rolled back even
    on success.  A verifier therefore cannot accidentally turn its proof into
    part of the adoption mutation.
    """
    if manifest.artifact != artifact:
        raise MigrationContentAdoptionError(
            "migration history manifest is not bound to the selected artifact"
        )
    if not SHA256_PATTERN.fullmatch(expected_manifest_sha256):
        raise MigrationContentAdoptionError(
            "expected manifest SHA256 must be a 64-character hex digest"
        )
    if manifest.content_sha256 != expected_manifest_sha256.lower():
        raise MigrationContentAdoptionError(
            "migration history manifest SHA256 does not match the selected "
            "release evidence"
        )
    live_entries = tuple((entry.name, entry.content_sha256) for entry in history)
    manifest_entries = tuple(
        (entry.name, entry.content_sha256) for entry in manifest.entries
    )
    if manifest_entries != live_entries:
        raise MigrationContentAdoptionError(
            "migration history manifest does not exactly describe the selected "
            "artifact's packaged history"
        )

    status = require_matching_content_identity(conn, history, ledger)
    requested = tuple(entry_names) if entry_names is not None else status.adoptable
    if len(requested) != len(set(requested)):
        raise MigrationContentAdoptionError("adoption entry_names contains duplicates")
    adoptable = set(status.adoptable)
    unavailable = [name for name in requested if name not in adoptable]
    if unavailable:
        raise MigrationContentAdoptionError(
            "adoption only updates applied rows whose digest is currently NULL; "
            "refused: " + ", ".join(unavailable)
        )

    by_name = {entry.name: entry for entry in history}
    if not requested:
        return ()
    conn.execute(f"SAVEPOINT {_VERIFY_SAVEPOINT}")
    try:
        for name in requested:
            verify_migration_entry_state_equivalence(
                conn,
                by_name[name],
                state_verifiers=state_verifiers,
            )
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {_VERIFY_SAVEPOINT}")
        conn.execute(f"RELEASE SAVEPOINT {_VERIFY_SAVEPOINT}")
        raise
    conn.execute(f"ROLLBACK TO SAVEPOINT {_VERIFY_SAVEPOINT}")
    conn.execute(f"RELEASE SAVEPOINT {_VERIFY_SAVEPOINT}")
    return requested


def adopt_legacy_content_identities(
    conn: Any,
    *,
    history: Sequence[MigrationEntry],
    ledger: LedgerContract,
    manifest: MigrationHistoryManifest,
    artifact: ArtifactIdentity,
    expected_manifest_sha256: str,
    adopted_by: str,
    write_evidence: EvidenceWriter,
    verify_evidence_immutability: EvidenceGuardVerifier,
    entry_names: Sequence[str] | None = None,
    adopted_at: str | None = None,
    state_verifiers: MigrationStateVerifierSource | None = None,
) -> Tuple[AdoptionRecord, ...]:
    """Adopt selected legacy rows, changing only NULL digests atomically.

    The manifest must describe the complete supplied history and be bound to
    the independently selected artifact identity.  ``entry_names`` allows a
    deliberately partial rollout; omitted means every currently adoptable row
    represented by this artifact.  Ledger-ahead rows remain untouched because
    this artifact cannot prove bytes it does not ship.
    """
    actor = adopted_by.strip()
    if not actor:
        raise MigrationContentAdoptionError("adopted_by must be non-empty")
    if not verify_evidence_immutability(conn):
        raise MigrationContentAdoptionError(
            "migration content adoption is not protected by the declared "
            "evidence and ledger-transition database guards"
        )
    requested = verify_legacy_content_adoption(
        conn,
        history=history,
        ledger=ledger,
        manifest=manifest,
        artifact=artifact,
        expected_manifest_sha256=expected_manifest_sha256,
        entry_names=entry_names,
        state_verifiers=state_verifiers,
    )
    if not requested:
        return ()

    digest_by_name = {entry.name: entry.content_sha256 for entry in manifest.entries}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    stamp = adopted_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records = tuple(
        AdoptionRecord(
            entry_name=name,
            content_sha256=digest_by_name[name],
            artifact_engine_version=artifact.engine_version,
            source_artifact=artifact.source_artifact,
            source_sha256=artifact.source_sha256,
            source_commit=artifact.source_commit,
            manifest_sha256=manifest.content_sha256,
            adopted_by=actor,
            adopted_at=stamp,
        )
        for name in requested
    )
    try:
        # The database guard permits a legacy NULL-to-digest transition only
        # after the matching immutable row exists. Both writes share this
        # transaction, so a race or failed update removes the evidence too.
        write_evidence(conn, records)
        for record in records:
            cursor = conn.execute(
                f"UPDATE {ledger.table} SET {ledger.digest_column} = {marker} "
                f"WHERE {ledger.entry_column} = {marker} "
                f"AND {ledger.digest_column} IS NULL",
                (record.content_sha256, record.entry_name),
            )
            if getattr(cursor, "rowcount", 0) != 1:
                raise MigrationContentAdoptionError(
                    f"{record.entry_name} changed before adoption could update "
                    "its NULL digest; no evidence was recorded"
                )
        # Catch a concurrent conflicting rewrite of any other common row before
        # append-only evidence and ledger updates commit together.
        require_matching_content_identity(conn, history, ledger)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return records


__all__ = [
    "AdoptionRecord",
    "EvidenceGuardVerifier",
    "EvidenceWriter",
    "MigrationContentAdoptionError",
    "MigrationStateVerifier",
    "MigrationStateVerifierResolver",
    "MigrationStateVerifierSource",
    "adopt_legacy_content_identities",
    "verify_legacy_content_adoption",
    "verify_migration_entry_state_equivalence",
]
