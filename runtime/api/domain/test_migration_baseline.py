"""Code baseline discovery, birth stamping and release artifact identity."""

import json
import sqlite3
import zipfile

import pytest

from yoke_core.domain.migration_baseline import baseline_from_source
from yoke_core.domain.migration_boot_apply import stamp_history, apply_pending
from yoke_core.domain.migration_history import HistoryError, ordered_entries
from yoke_core.domain.migration_history_manifest import (
    ArtifactIdentity,
    manifest_from_content,
)
from yoke_core.domain.migration_yoke_ledger import (
    ensure_yoke_migration_ledger,
    YOKE_LEDGER_CONTRACT,
)
from yoke_core.tools.migration_history_release_artifact import (
    _wheel_history,
    _wheel_baselines,
    materialize_core_wheel_history,
)


def _package(directory, **overrides):
    directory.mkdir(exist_ok=True)
    declaration = {
        "name": "0106_baseline",
        "content_sha256": "a" * 64,
        "minimum_serving_version": "next-release",
    }
    declaration.update(overrides)
    raw = ("HISTORY_BASELINE = " + repr(declaration) + "\n").encode()
    (directory / "__init__.py").write_bytes(raw)
    return raw


def test_baseline_survives_removal_of_temporary_predecessor_input(tmp_path):
    _package(
        tmp_path,
        predecessor_manifest="released_history_digests.json",
        adoption_evidence_table="migration_content_adoptions",
    )
    manifest = tmp_path / "released_history_digests.json"
    manifest.write_text(json.dumps({"0001_old": "b" * 64}))
    (before,) = ordered_entries(tmp_path)
    manifest.unlink()
    _package(tmp_path)
    (after,) = ordered_entries(tmp_path)
    assert (before.name, before.content_sha256, before.minimum_serving_version) == (
        after.name,
        after.content_sha256,
        after.minimum_serving_version,
    )
    assert not list(tmp_path.glob("[0-9]*.py"))


@pytest.mark.parametrize(
    "bad",
    [
        {"content_sha256": "wrong"},
        {"name": "not_numbered"},
        {
            "predecessor_manifest": "../unsafe.json",
            "adoption_evidence_table": "migration_content_adoptions",
        },
        {"minimum_serving_version": "not-a-version"},
    ],
)
def test_malformed_baseline_refuses_with_recovery(tmp_path, bad):
    with pytest.raises((HistoryError, ValueError), match="baseline|valid version"):
        baseline_from_source(_package(tmp_path, **bad), tmp_path)


def test_newborn_stamps_baseline_floor_and_later_entry_applies(tmp_path):
    _package(tmp_path)
    conn = sqlite3.connect(":memory:")
    ensure_yoke_migration_ledger(conn)
    assert stamp_history(
        conn,
        ordered_entries(tmp_path),
        ledger=YOKE_LEDGER_CONTRACT,
        applied_by="birth",
        administering_env="",
        running_version="9.0.0",
    ) == ("0106_baseline",)
    assert conn.execute(
        "SELECT migration_name,content_sha256,minimum_serving_version FROM applied_migrations"
    ).fetchall() == [("0106_baseline", "a" * 64, "9.0.0")]
    (tmp_path / "0107_tail.py").write_text(
        "def apply(conn):\n    conn.execute('CREATE TABLE tail_proof(value INTEGER)')\n"
    )
    result = apply_pending(
        conn,
        history=ordered_entries(tmp_path),
        ledger=YOKE_LEDGER_CONTRACT,
        applied_by="boot",
        administering_env="",
        running_version="9.0.0",
        attribution={
            "session_id": "boot",
            "actor_id": "boot",
            "source_branch": "main",
            "source_commit": "a" * 40,
        },
        model_name="primary",
        dump_backup=lambda *_: pytest.fail("named restore point supplied"),
        external_restore_point="snapshot:baseline-tail",
    )
    assert result.applied == ("0107_tail",)
    assert conn.execute("SELECT count(*) FROM tail_proof").fetchone() == (0,)


def test_wheel_manifest_and_materialization_carry_baseline_without_scripts(tmp_path):
    raw = _package(tmp_path / "source")
    wheel = tmp_path / "core.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("yoke_core/domain/migrations/__init__.py", raw)
    artifact = ArtifactIdentity(
        engine_version="9.0.0",
        source_artifact="core.whl",
        source_sha256="b" * 64,
        source_commit="c" * 40,
    )
    manifest = manifest_from_content(
        _wheel_history(wheel), artifact, baselines=_wheel_baselines(wheel)
    )
    assert [(entry.name, entry.content_sha256) for entry in manifest.entries] == [
        ("0106_baseline", "a" * 64)
    ]
    entries = materialize_core_wheel_history(wheel, tmp_path / "materialized")
    assert [(entry.name, entry.content_sha256) for entry in entries] == [
        ("0106_baseline", "a" * 64)
    ]
