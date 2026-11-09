"""Folded baseline identities work without replayable migration scripts."""

import json
import zipfile

import pytest

from runtime.api.domain.migration_boot_test_helpers import (
    apply_pending,
    connection,
    entry_database,
    stamp_history,
)
from yoke_core.domain.migration_content_identity import (
    MigrationContentMismatch,
    require_matching_content_identity,
)
from yoke_core.domain.migration_folded_history import RELEASED_DIGESTS_NAME
from yoke_core.domain.migration_history import HistoryError, ordered_entries
from yoke_core.domain.migration_history_manifest import (
    ArtifactIdentity,
    load_manifest,
    manifest_from_content,
    manifest_from_history,
    write_manifest,
)
from yoke_core.domain.migration_yoke_ledger import YOKE_LEDGER_CONTRACT
from yoke_core.tools.migration_history_release_artifact import (
    CORE_HISTORY_PREFIX,
    _wheel_folded,
    _wheel_history,
    materialize_core_wheel_history,
)

NAME = "8000_folded_baseline"
DIGEST = "a" * 64
FLOOR = "1.2.3"


def _fold(directory, *, floor=FLOOR, name=NAME):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / RELEASED_DIGESTS_NAME).write_text(
        json.dumps(
            {
                name: {"content_sha256": DIGEST, "minimum_serving_version": floor},
            }
        )
    )
    return ordered_entries(directory)


@pytest.fixture(params=["sqlite", "postgres"])
def database(request, tmp_path):
    if request.param == "sqlite":
        conn = connection()
        try:
            yield conn
        finally:
            conn.close()
    else:
        with entry_database(tmp_path / "database", "empty") as conn:
            yield conn


@pytest.mark.parametrize("floor", [FLOOR, None])
def test_fresh_database_stamps_folded_identity_and_floor(database, tmp_path, floor):
    history = _fold(tmp_path / "history", floor=floor)
    assert not history[0].path.exists()
    assert stamp_history(database, history, applied_by="birth") == (NAME,)
    row = database.execute(
        "SELECT content_sha256, minimum_serving_version FROM applied_migrations "
        f"WHERE migration_name = '{NAME}'"
    ).fetchone()
    assert tuple(row) == (DIGEST, floor)
    status = require_matching_content_identity(database, history, YOKE_LEDGER_CONTRACT)
    assert NAME in status.verified
    assert not apply_pending(
        database,
        history=history,
        applied_by="boot",
        running_version="2.0.0",
    ).changed


@pytest.mark.parametrize("recorded_prefix", [False, True])
def test_upgrade_missing_folded_entry_refuses_before_restore(
    database, tmp_path, recorded_prefix
):
    history = _fold(tmp_path / "history")
    if recorded_prefix:
        # An upgraded database can be past one folded entry yet owe another.
        stamp_history(database, history, applied_by="prior-build")
        manifest = tmp_path / "history" / RELEASED_DIGESTS_NAME
        payload = json.loads(manifest.read_text())
        payload["8001_missing_folded"] = {
            "content_sha256": "b" * 64,
            "minimum_serving_version": None,
        }
        manifest.write_text(json.dumps(payload))
        history = ordered_entries(manifest.parent)
    with pytest.raises(
        HistoryError, match="migration_folded_history_missing"
    ) as refusal:
        apply_pending(
            database, history=history, applied_by="boot", running_version="2.0.0"
        )
    missing = "8001_missing_folded" if recorded_prefix else NAME
    assert missing in str(refusal.value)
    assert "earlier build" in str(refusal.value)
    assert "pre-ledger" in str(refusal.value)


def test_folded_digest_mismatch_still_refuses(database, tmp_path):
    history = _fold(tmp_path / "history")
    stamp_history(database, history, applied_by="birth")
    manifest = tmp_path / "history" / RELEASED_DIGESTS_NAME
    manifest.write_text(manifest.read_text().replace(DIGEST, "b" * 64))
    with pytest.raises(MigrationContentMismatch, match=NAME):
        require_matching_content_identity(
            database, ordered_entries(manifest.parent), YOKE_LEDGER_CONTRACT
        )


def test_empty_folded_map_preserves_live_history(database, tmp_path):
    directory = tmp_path / "history"
    directory.mkdir()
    (directory / "8001_live.py").write_text("def apply(conn): pass\n")
    original = ordered_entries(directory)
    (directory / RELEASED_DIGESTS_NAME).write_text("{}")
    assert ordered_entries(directory) == original
    assert stamp_history(database, original, applied_by="birth") == ("8001_live",)


@pytest.mark.parametrize("floor", ["next-release", "", "nonsense", 2])
def test_folded_entry_requires_resolved_serving_floor(tmp_path, floor):
    with pytest.raises(HistoryError, match="invalid identity"):
        _fold(tmp_path, floor=floor)


@pytest.mark.parametrize("live_name", [NAME, "8000_other_name"])
def test_folded_entries_cannot_collide_with_scripts(tmp_path, live_name):
    (tmp_path / f"{live_name}.py").write_text("def apply(conn): pass\n")
    with pytest.raises(HistoryError, match="collides"):
        _fold(tmp_path)


def test_folded_entries_have_unique_ordinals(tmp_path):
    _fold(tmp_path)
    manifest = tmp_path / RELEASED_DIGESTS_NAME
    payload = json.loads(manifest.read_text())
    payload["8000_other"] = payload[NAME]
    manifest.write_text(json.dumps(payload))
    with pytest.raises(HistoryError, match="collides"):
        ordered_entries(tmp_path)


def test_release_manifest_and_wheel_materialization_include_folded_entries(tmp_path):
    history = _fold(tmp_path / "history", floor=None)
    artifact = ArtifactIdentity("2.0.0", "core.whl", "c" * 64, "d" * 40)
    expected = manifest_from_history(history, artifact)
    manifest_path = tmp_path / "migration-history.json"
    write_manifest(manifest_path, expected)
    assert load_manifest(manifest_path) == expected
    wheel = tmp_path / "core.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            CORE_HISTORY_PREFIX + RELEASED_DIGESTS_NAME,
            (tmp_path / "history" / RELEASED_DIGESTS_NAME).read_bytes(),
        )
    actual = manifest_from_content(
        _wheel_history(wheel), artifact, folded=_wheel_folded(wheel)
    )
    assert actual == expected
    extracted = materialize_core_wheel_history(wheel, tmp_path / "extracted")
    assert manifest_from_history(extracted, artifact) == expected
    assert not extracted[0].path.exists()


def test_upgrade_past_folded_prefix_applies_live_tail(database, tmp_path):
    history = _fold(tmp_path / "history")
    stamp_history(database, history, applied_by="prior-build")
    (tmp_path / "history" / "8001_live.py").write_text(
        "def apply(conn):\n    conn.execute('CREATE TABLE folded_tail_proof (value TEXT)')\n"
    )
    outcome = apply_pending(
        database,
        history=ordered_entries(tmp_path / "history"),
        applied_by="boot",
        running_version="2.0.0",
        external_restore_point="snapshot:upgrade-proof",
    )
    assert outcome.applied == ("8001_live",)
    assert database.execute("SELECT count(*) FROM folded_tail_proof").fetchone()[0] == 0


def test_integration_target_retains_folded_history_names(tmp_path):
    from runtime.api.domain import test_migration_history_integration as support
    from yoke_core.domain.migration_content_identity import raw_content_sha256
    from yoke_core.domain.migration_history_integration import history_names_at_ref

    repo = support.lane.__wrapped__(tmp_path)
    directory = repo / support.MODULES_DIR
    entry = directory / "0013_existing.py"
    digest = raw_content_sha256(entry.read_bytes())
    entry.unlink()
    (directory / RELEASED_DIGESTS_NAME).write_text(
        json.dumps(
            {
                "0013_existing": {
                    "content_sha256": digest,
                    "minimum_serving_version": None,
                },
            }
        )
    )
    support._entry(repo, "0014_next")
    support._merge(repo, "0014_next")
    support._git(repo, "add", "-A")
    support._git(repo, "commit", "-qm", "fold baseline and extend")
    assert history_names_at_ref(repo, "HEAD", support.MODULES_DIR) == (
        "0013_existing",
        "0014_next",
    )
    support._git(repo, "branch", "-f", "main", "HEAD")
    support._entry(repo, "0015_next")
    support._merge(repo, "0015_next")
