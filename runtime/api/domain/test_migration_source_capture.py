"""Migration execution and ledger evidence share one captured source image."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from runtime.api.domain.migration_boot_test_helpers import (
    RESTORE_POINT,
    applied_names,
    apply_pending,
    connection,
    marks,
    stamp_history,
)
from yoke_core.domain.migration_boot_apply import EntryFailed
from yoke_core.domain.migration_history import load_migration_module, ordered_entries


def _entry_body(mark: str) -> bytes:
    return (
        f"def apply(conn):\n    conn.execute(\"INSERT INTO marks VALUES ('{mark}')\")\n"
    ).encode()


def test_loader_executes_the_explicitly_captured_source(tmp_path: Path) -> None:
    path = tmp_path / "0001_captured.py"
    captured = _entry_body("captured")
    path.write_bytes(captured)
    path.write_bytes(_entry_body("replacement"))

    module = load_migration_module(
        path,
        "0001_captured",
        source_bytes=captured,
    )
    conn = connection()
    module.apply(conn)

    assert marks(conn) == ["captured"]


def test_apply_rolls_back_when_entry_rewrites_its_source(tmp_path: Path) -> None:
    path = tmp_path / "0001_rewrites_source.py"
    path.write_text(
        "from pathlib import Path\n"
        "def apply(conn):\n"
        "    conn.execute(\"INSERT INTO marks VALUES ('before-rewrite')\")\n"
        "    Path(__file__).write_text('def apply(conn):\\n    pass\\n')\n"
    )
    history = ordered_entries(tmp_path)
    conn = connection()

    with pytest.raises(EntryFailed, match="source changed"):
        apply_pending(
            conn,
            history=history,
            applied_by="test",
            running_version="",
            external_restore_point=RESTORE_POINT,
        )

    assert marks(conn) == []
    assert applied_names(conn) == set()
    state = conn.execute(
        "SELECT state FROM migration_audit "
        "WHERE migration_name = '0001_rewrites_source'"
    ).fetchone()
    assert state == ("live_verify_failed",)


def test_applied_digest_names_the_executed_source(tmp_path: Path) -> None:
    path = tmp_path / "0001_stable.py"
    source = _entry_body("stable")
    path.write_bytes(source)
    conn = connection()

    apply_pending(
        conn,
        history=ordered_entries(tmp_path),
        applied_by="test",
        running_version="",
        external_restore_point=RESTORE_POINT,
    )

    digest = conn.execute(
        "SELECT content_sha256 FROM applied_migrations "
        "WHERE migration_name = '0001_stable'"
    ).fetchone()
    assert digest == (hashlib.sha256(source).hexdigest(),)


def test_birth_stamp_is_atomic_when_import_rewrites_source(tmp_path: Path) -> None:
    (tmp_path / "0001_stable.py").write_bytes(_entry_body("not-run"))
    path = tmp_path / "0002_rewrites_on_import.py"
    path.write_text(
        "from pathlib import Path\n"
        "Path(__file__).write_text('def apply(conn):\\n    pass\\n')\n"
        "def apply(conn):\n"
        "    pass\n"
    )
    conn = connection()

    with pytest.raises(EntryFailed, match="source changed"):
        stamp_history(conn, ordered_entries(tmp_path), applied_by="birth")

    assert applied_names(conn) == set()
