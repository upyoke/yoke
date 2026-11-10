"""Code baseline discovery, birth stamping and release artifact identity."""

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


@pytest.mark.parametrize(
    "bad",
    [
        {"content_sha256": "wrong"},
        {"name": "not_numbered"},
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


def test_current_baseline_boot_applies_nothing(tmp_path):
    _package(tmp_path)
    conn = sqlite3.connect(":memory:")
    ensure_yoke_migration_ledger(conn)
    history = ordered_entries(tmp_path)
    stamp_history(
        conn,
        history,
        ledger=YOKE_LEDGER_CONTRACT,
        applied_by="birth",
        administering_env="",
        running_version="9.0.0",
    )
    result = apply_pending(
        conn,
        history=history,
        ledger=YOKE_LEDGER_CONTRACT,
        applied_by="boot",
        administering_env="",
        running_version="9.0.0",
        attribution={},
        model_name="",
    )
    assert result.applied == ()
    assert result.restore_point is None


def test_existing_ledger_without_baseline_refuses_before_restore(tmp_path):
    _package(tmp_path)
    conn = sqlite3.connect(":memory:")
    ensure_yoke_migration_ledger(conn)
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by, content_sha256) VALUES (?, ?, ?, ?)",
        ("0001_old", "2026-01-01T00:00:00.000000Z", "old", "b" * 64),
    )
    conn.commit()
    with pytest.raises(HistoryError, match="migration_baseline_missing:.*restore"):
        apply_pending(
            conn,
            history=ordered_entries(tmp_path),
            ledger=YOKE_LEDGER_CONTRACT,
            applied_by="boot",
            administering_env="",
            running_version="9.0.0",
            attribution={},
            model_name="",
            dump_backup=lambda *_: pytest.fail("must refuse before restore"),
        )
    assert conn.execute("SELECT migration_name FROM applied_migrations").fetchall() == [
        ("0001_old",)
    ]


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
