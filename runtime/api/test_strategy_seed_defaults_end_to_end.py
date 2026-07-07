"""End-to-end cold start: ``yoke strategy seed-defaults`` through the
real CLI + dispatcher against a disposable Postgres, then idempotent
re-run. Sibling of ``test_strategy_db_end_to_end.py`` (split for the
authored-file line cap)."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from yoke_cli.main import main as cli_main
from yoke_core.domain import strategy_docs as sd
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.handlers._strategy_docs_test_helpers import seed_session
from yoke_core.domain.strategy_docs_defaults import DEFAULT_STRATEGY_DOC_SLUGS
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

OPERATOR = "e2e-seed-operator"
COLD_PROJECT = 2  # schema-seeded project with no strategy rows


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        reset_registry_for_tests()
        register_all_handlers()
        conn = connect_test_db(db_path)
        try:
            seed_session(conn, OPERATOR)
        finally:
            conn.close()
        yield db_path


def _envelope(*argv: str) -> dict:
    out, err = io.StringIO(), io.StringIO()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("YOKE_SESSION_ID", OPERATOR)
        with redirect_stdout(out), redirect_stderr(err):
            cli_main([*argv, "--project", str(COLD_PROJECT), "--json"])
    text = out.getvalue() if out.getvalue().strip() else err.getvalue()
    return json.loads(text[text.index("{"):])


def test_seed_defaults_cold_start_through_real_cli(world) -> None:
    """A project with zero rows cold-starts via the CLI; re-run no-ops."""
    seeded = _envelope("strategy", "seed-defaults")
    assert seeded["success"] is True
    assert seeded["result"]["already_seeded"] is False
    assert seeded["result"]["seeded"] == list(DEFAULT_STRATEGY_DOC_SLUGS)

    again = _envelope("strategy", "seed-defaults")
    assert again["success"] is True
    assert again["result"]["already_seeded"] is True

    conn = connect_test_db(world)
    try:
        count = conn.execute(
            f"SELECT COUNT(*) FROM {sd.STRATEGY_DOCS_TABLE} "
            "WHERE project_id = %s",
            (COLD_PROJECT,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert int(count) == len(DEFAULT_STRATEGY_DOC_SLUGS)
