"""CLI surface tests for yoke_core.domain.shepherd."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from runtime.api.conftest import insert_item


def _run_shepherd_cli(args):
    """Invoke the CLI against the fixture-owned disposable Postgres DB."""
    env = dict(os.environ)
    env["YOKE_DB_INIT_ALLOW"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "yoke_core.cli.db_router", "shepherd", *args],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def shepherd_db(test_db):
    """Own a fresh full-schema database and real pinned epics per test."""
    for item_id in (1, 2, 3):
        insert_item(test_db, id=item_id, workflow_id="epic", status="planned")
    test_db.commit()
    return test_db


def test_verdict_inserts_minimal_row(shepherd_db):
    """The ``verdict`` subcommand inserts with the four required positionals."""
    result = _run_shepherd_cli(
        ["verdict", "YOK-1", "planning_to_plan_drafted", "test-worker", "READY"],
    )
    assert result.returncode == 0, result.stderr
    verdict_id = result.stdout.strip()
    assert verdict_id.isdigit()


def test_verdict_inserts_with_caveats(shepherd_db):
    result = _run_shepherd_cli(
        [
            "verdict",
            "YOK-2",
            "planning_to_plan_drafted",
            "test-worker",
            "CAVEATS",
            "caveat body",
        ],
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
            "YOK-3",
            "planning_to_plan_drafted",
            "test-worker",
            "READY",
            "",
            "9f33bc49-bc9d-4bb9-a0b3-b7927bf8880a",
        ],
    )
    assert result.returncode == 0, result.stderr
    assert "ignoring extra positional argument" in result.stderr
    assert result.stdout.strip().isdigit()


def test_shepherd_verdicts_table_has_canonical_columns(shepherd_db):
    """Schema regression: the canonical column set is exact — no stranded
    columns from retired session models."""
    rows = shepherd_db.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() "
        "AND table_name = 'shepherd_verdicts'"
    ).fetchall()
    cols = {row[0] for row in rows}
    assert cols == {
        "id",
        "public_ref",
        "archived_item_key",
        "transition",
        "worker",
        "verdict",
        "caveats",
        "attempt",
        "created_at",
    }
