"""Browser QA — deployed-SHA freshness validation.

``_validate_deployed_sha`` is a pure comparison over the
``qa.browser_context.get`` payload; the row lookup itself is covered by the
handler tests in ``runtime/api/test_api_qa_browser_function.py``.
Ephemeral-environment seeding helpers live alongside the scenario suite that
uses them (the fake context fetch reads the per-test DB).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import browser_qa, db_backend
from yoke_core.domain.browser_qa_test_helpers import (
    _patch_external_deps,
    _run_scenario,
    _seed_item,
    _seed_requirement,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        yield path


def _ensure_ephemeral_table(db_path: str) -> None:
    """Create the ephemeral_environments table if it doesn't exist."""
    conn = connect_test_db(db_path)
    execute_schema_script(conn, """
        CREATE TABLE IF NOT EXISTS ephemeral_environments (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            branch TEXT NOT NULL,
            item TEXT,
            workflow_run_id TEXT,
            github_ref TEXT,
            port_api INTEGER,
            port_web INTEGER,
            url TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT,
            stopped_at TEXT,
            health_check_url TEXT,
            deployed_sha TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, branch)
        );
    """)
    conn.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
        "VALUES (100, 'testproj', 'Test Project', 'YOK', '2026-01-01T00:00:00Z') "
        "ON CONFLICT(id) DO NOTHING",
    )
    conn.commit()
    conn.close()


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_ephemeral_env(
    db_path: str,
    project: str,
    branch: str,
    deployed_sha: str = "",
) -> int:
    """Seed an ephemeral_environments row and return its id."""
    _ensure_ephemeral_table(db_path)
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    cur = conn.execute(
        f"""
        INSERT INTO ephemeral_environments (project_id, branch, deployed_sha, status, created_at)
        VALUES ({p}, {p}, {p}, 'healthy', {p}) RETURNING id
        """,
        (100, branch, deployed_sha, "2026-01-01T00:00:00Z"),
    )
    env_id = int(cur.fetchone()[0])
    conn.commit()
    conn.close()
    return env_id


class TestDeployedShaFreshness:
    """_validate_deployed_sha (pure compare) and the scenario freshness gate."""

    def test_sha_match_passes(self) -> None:
        """AC-2/AC-4: matching SHA passes validation and logs success."""
        with mock.patch("yoke_core.domain.browser_qa._log") as mock_log:
            err = browser_qa._validate_deployed_sha(
                "testproj", "YOK-999", "abc123",
                deployed_sha="abc123", deployment_recorded=True,
            )
        assert err is None
        mock_log.assert_called_once_with(
            "Freshness check passed: branch=YOK-999, sha=abc123",
        )

    def test_sha_mismatch_returns_error(self) -> None:
        """AC-2: mismatch returns error with both SHAs in the message."""
        err = browser_qa._validate_deployed_sha(
            "testproj", "YOK-999", "new222",
            deployed_sha="old111", deployment_recorded=True,
        )
        assert err is not None
        assert "old111" in err
        assert "new222" in err

    def test_no_env_row_returns_error(self) -> None:
        """AC-3: missing env row returns clear 'no deployment recorded' error."""
        err = browser_qa._validate_deployed_sha(
            "testproj", "YOK-999", "abc123",
            deployed_sha=None, deployment_recorded=False,
        )
        assert err is not None
        assert "No ephemeral environment record" in err
        assert "YOK-999" in err

    def test_empty_deployed_sha_returns_error(self) -> None:
        """AC-3: env row exists but deployed_sha is empty."""
        err = browser_qa._validate_deployed_sha(
            "testproj", "YOK-999", "abc123",
            deployed_sha=None, deployment_recorded=True,
        )
        assert err is not None
        assert "no deployed_sha" in err

    def test_execute_scenario_blocks_on_sha_mismatch(self, db_path: str) -> None:
        """AC-1/AC-2: execute_scenario hard-blocks when SHA doesn't match."""
        _seed_item(db_path, 500)
        _seed_requirement(
            db_path, 500, "browser_smoke",
            {"base_url": "http://localhost:9999", "steps": [{"action": "navigate"}]},
        )
        _seed_ephemeral_env(db_path, "testproj", "YOK-500", deployed_sha="stale_sha")

        patches = _patch_external_deps(db_path)
        for patcher in patches:
            patcher.start()
        try:
            result = browser_qa.execute_scenario(
                item_id=500,
                project="testproj",
                base_url="http://localhost:9999",
                expected_branch="YOK-500",
                expected_sha="fresh_sha",
            )
        finally:
            for patcher in reversed(patches):
                patcher.stop()

        assert result.verdict == "error"
        assert result.note == "sha_mismatch"

    def test_execute_scenario_rejects_partial_freshness_inputs(self, db_path: str) -> None:
        """Polish: partial freshness args must fail closed instead of skipping validation."""
        _seed_item(db_path, 502)
        _seed_requirement(
            db_path, 502, "browser_smoke",
            {"base_url": "http://localhost:9999", "steps": [{"action": "navigate"}]},
        )

        result = browser_qa.execute_scenario(
            item_id=502,
            project="testproj",
            base_url="http://localhost:9999",
            expected_branch="YOK-502",
        )

        assert result.verdict == "error"
        assert result.note == "freshness_args_incomplete"

    def test_execute_scenario_passes_without_freshness_args(self, db_path: str) -> None:
        """Backward compat: omitting expected_branch/sha skips freshness check."""
        _seed_item(db_path, 501)
        _seed_requirement(
            db_path, 501, "browser_smoke",
            {"base_url": "http://localhost:9999", "steps": [{"action": "navigate"}]},
        )

        result = _run_scenario(
            db_path, 501,
            execute_step_responses=[{"success": True, "artifacts": []}],
        )
        assert result.verdict == "pass"

    def test_main_forwards_expected_branch_and_sha(self) -> None:
        """AC-1: CLI wires expected freshness args into execute_scenario."""
        with mock.patch(
            "yoke_core.domain.browser_qa.execute_scenario",
            return_value=browser_qa.ScenarioResult(),
        ) as mock_execute:
            exit_code = browser_qa.main([
                "--item-id", "100",
                "--project", "test",
                "--expected-branch", "YOK-100",
                "--expected-sha", "abc123",
            ])

        assert exit_code == 0
        mock_execute.assert_called_once_with(
            item_id=100,
            project="test",
            base_url="",
            expected_branch="YOK-100",
            expected_sha="abc123",
        )

    def test_execute_scenario_records_code_identity_in_raw_result(
        self, tmp_path: Path, db_path: str
    ) -> None:
        """Browser QA runs persist the branch/SHA they executed against."""
        _seed_item(db_path, 503)
        req_id = _seed_requirement(
            db_path, 503, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {"action": "screenshot", "capture": True, "label": "home"},
                ],
            },
        )
        _seed_ephemeral_env(db_path, "testproj", "YOK-503", deployed_sha="sha503")
        shot_file = tmp_path / "home.png"
        shot_file.write_bytes(b"PNG")

        patches = _patch_external_deps(
            db_path,
            execute_step_responses=[
                {"success": True, "artifacts": []},
                {"success": True, "artifacts": [str(shot_file)]},
            ],
        )
        for patcher in patches:
            patcher.start()
        try:
            result = browser_qa.execute_scenario(
                item_id=503,
                project="testproj",
                base_url="http://localhost:9999",
                expected_branch="YOK-503",
                expected_sha="sha503",
            )
        finally:
            for patcher in reversed(patches):
                patcher.stop()

        assert result.verdict == "pass"
        assert result.runs[0].code_identity == {
            "branch": "YOK-503",
            "sha": "sha503",
        }

        conn = connect_test_db(db_path)
        p = _placeholder(conn)
        row = conn.execute(
            f"SELECT raw_result FROM qa_runs WHERE qa_requirement_id = {p}",
            (req_id,),
        ).fetchone()
        conn.close()

        assert row is not None
        payload = json.loads(row[0])
        assert payload["code_identity"] == {"branch": "YOK-503", "sha": "sha503"}
        assert payload["freshness_validated"] is True
