"""Release-identity refusal coverage for migration content adoption."""

from pathlib import Path

import pytest

from runtime.api.domain.test_migration_content_identity import (
    SOURCE_COMMIT,
    _adoptable_history,
    _connection,
)
from yoke_core.domain.migration_content_adoption import MigrationContentAdoptionError
from yoke_core.domain.migration_history_manifest import (
    ArtifactIdentity,
    manifest_from_history,
)
from yoke_core.domain.migration_yoke_ledger import (
    YOKE_ADOPTION_EVIDENCE_TABLE,
    adopt_yoke_legacy_content_identities,
)


@pytest.mark.parametrize("wrong_identity", ["source_commit", "manifest_sha256"])
def test_wrong_release_identity_refuses_before_adoption(
    tmp_path: Path,
    wrong_identity: str,
) -> None:
    conn = _connection()
    history = _adoptable_history(tmp_path, "0001_first")
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
    selected_artifact = artifact
    expected_digest = manifest.content_sha256
    if wrong_identity == "source_commit":
        selected_artifact = ArtifactIdentity(
            "1.2.3",
            "yoke_core-1.2.3.whl",
            "a" * 64,
            "d" * 40,
        )
    else:
        expected_digest = "f" * 64

    with pytest.raises(MigrationContentAdoptionError):
        adopt_yoke_legacy_content_identities(
            conn,
            history=history,
            manifest=manifest,
            artifact=selected_artifact,
            expected_manifest_sha256=expected_digest,
            adopted_by="operator:test",
        )

    digest = conn.execute("SELECT content_sha256 FROM applied_migrations").fetchone()[0]
    evidence_count = conn.execute(
        f"SELECT count(*) FROM {YOKE_ADOPTION_EVIDENCE_TABLE}"
    ).fetchone()[0]
    assert digest is None
    assert evidence_count == 0
