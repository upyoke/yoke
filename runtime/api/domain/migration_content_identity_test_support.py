# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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
