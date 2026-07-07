"""CLI surface tests for yoke_core.domain.shepherd."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.shepherd_dependency import VALID_SOURCES


def _run_shepherd_cli(args, db_path):
    """Invoke the shepherd CLI with ``YOKE_DB`` pinned to a temp DB."""
    env = dict(os.environ)
    env["YOKE_DB"] = db_path
    env["YOKE_DB_INIT_ALLOW"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "yoke_core.cli.db_router", "shepherd", *args],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def shepherd_db():
    """Create a temp DB with full schema + shepherd tables bootstrapped."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    env = dict(os.environ)
    env["YOKE_DB"] = path
    env["YOKE_DB_INIT_ALLOW"] = "1"
    init_result = subprocess.run(
        [sys.executable, "-m", "yoke_core.cli.db_router", "init"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert init_result.returncode == 0, init_result.stderr
    # Bootstrap chain swallows shepherd init errors; explicitly create the
    # shepherd tables on the temp DB so the verdict CLI has somewhere to
    # write.
    shepherd_init = subprocess.run(
        [sys.executable, "-m", "yoke_core.cli.db_router", "shepherd", "init"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert shepherd_init.returncode == 0, shepherd_init.stderr
    yield path
    os.unlink(path)


def test_verdict_inserts_minimal_row(shepherd_db):
    """The ``verdict`` subcommand inserts with the four required positionals."""
    result = _run_shepherd_cli(
        ["verdict", "TEST-1", "test_transition", "test-worker", "READY"],
        shepherd_db,
    )
    assert result.returncode == 0, result.stderr
    verdict_id = result.stdout.strip()
    assert verdict_id.isdigit()


def test_verdict_inserts_with_caveats(shepherd_db):
    result = _run_shepherd_cli(
        ["verdict", "TEST-2", "test_transition", "test-worker", "CAVEATS", "caveat body"],
        shepherd_db,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().isdigit()


def test_verdict_ignores_extra_trailing_positional(shepherd_db):
    """Regression: a 6th positional must be accepted and ignored, not
    crash the insert. Older callers passed an extra trailing argument
    referencing a retired schema column; the CLI must tolerate that
    during the rollout window."""
    result = _run_shepherd_cli(
        [
            "verdict",
            "TEST-3",
            "test_transition",
            "test-worker",
            "READY",
            "",
            "9f33bc49-bc9d-4bb9-a0b3-b7927bf8880a",
        ],
        shepherd_db,
    )
    assert result.returncode == 0, result.stderr
    assert "ignoring extra positional argument" in result.stderr
    assert result.stdout.strip().isdigit()


def test_shepherd_verdicts_table_has_canonical_columns(shepherd_db):
    """Schema regression: the canonical column set is exact — no stranded
    columns from retired session models."""
    conn = db_backend.connect()
    try:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = 'shepherd_verdicts'"
        ).fetchall()
    finally:
        conn.close()
    cols = {row[0] for row in rows}
    assert cols == {
        "id", "item", "transition", "worker", "verdict",
        "caveats", "attempt", "created_at",
    }


def test_dependency_add_help_lists_positional_source_values(shepherd_db):
    result = _run_shepherd_cli(["dependency-add", "--help"], shepherd_db)

    assert result.returncode == 0, result.stderr
    assert "dependency-add <dependent> <blocking> <source>" in result.stdout
    for source in VALID_SOURCES:
        assert source in result.stdout
    assert "--source" not in result.stdout


def test_dependency_add_invalid_source_is_actionable(shepherd_db):
    result = _run_shepherd_cli(
        ["dependency-add", "YOK-1", "YOK-2", "agent"],
        shepherd_db,
    )

    assert result.returncode == 2
    assert "source must be" in result.stderr
    for source in VALID_SOURCES:
        assert source in result.stderr
    assert "sqlite3.IntegrityError" not in result.stderr
