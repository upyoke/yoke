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

from yoke_core.domain import browser_qa, browser_qa_freshness, db_backend
from yoke_core.domain import browser_qa_preview_identity as preview_identity
from runtime.api.domain.browser_qa_test_helpers import (
    _browser_verdict_assertion,
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
        """Matching SHA passes validation and names the evidence source."""
        with mock.patch("yoke_core.domain.browser_qa._log") as mock_log:
            err = browser_qa._validate_deployed_sha(
                "testproj", "YOK-999", "abc123",
                deployed_sha="abc123", deployment_recorded=True,
            )
        assert err is None
        mock_log.assert_called_once_with(
            "Freshness check passed against the recorded deployment: "
            "branch=YOK-999, sha=abc123",
        )

    def test_sha_mismatch_returns_error(self) -> None:
        """Mismatch returns error with both SHAs in the message."""
        err = browser_qa._validate_deployed_sha(
            "testproj", "YOK-999", "new222",
            deployed_sha="old111", deployment_recorded=True,
        )
        assert err is not None
        assert err.reason == browser_qa_freshness.SHA_MISMATCH
        assert "old111" in err.message
        assert "new222" in err.message

    def test_no_env_row_is_not_reported_as_a_mismatch(self) -> None:
        """An absent record is its own outcome, never a SHA mismatch.

        Collapsing the two sends the reader hunting for a stale deploy that
        never existed — the environment served the right commit, nothing
        recorded that it had.
        """
        err = browser_qa._validate_deployed_sha(
            "testproj", "YOK-999", "abc123",
            deployed_sha=None, deployment_recorded=False,
            identity_target=preview_identity.PreviewIdentityTarget(
                unconfigured=True
            ),
        )
        assert err is not None
        assert err.reason == browser_qa_freshness.DEPLOYMENT_RECORD_MISSING
        assert err.reason != browser_qa_freshness.SHA_MISMATCH
        assert "No ephemeral environment record" in err.message
        assert "YOK-999" in err.message

    def test_empty_deployed_sha_is_its_own_reason(self) -> None:
        """A row with no recorded commit is neither absent nor mismatched."""
        err = browser_qa._validate_deployed_sha(
            "testproj", "YOK-999", "abc123",
            deployed_sha=None, deployment_recorded=True,
        )
        assert err is not None
        assert err.reason == browser_qa_freshness.DEPLOYED_SHA_UNKNOWN
        assert "records no deployed commit" in err.message

    def test_execute_scenario_blocks_on_sha_mismatch(self, db_path: str) -> None:
        """Execute_scenario hard-blocks when SHA doesn't match."""
        _seed_item(db_path, 500)
        req_id = _seed_requirement(
            db_path, 500, "browser-check",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    _browser_verdict_assertion(),
                ],
            },
        )
        _seed_ephemeral_env(db_path, "testproj", "YOK-500", deployed_sha="stale_sha")

        patches = _patch_external_deps(db_path)
        for patcher in patches:
            patcher.start()
        try:
            result = browser_qa.execute_scenario(
                item_id=500,
                project="testproj",
                requirement_id=req_id,
                base_url="http://localhost:9999",
                expected_branch="YOK-500",
                expected_sha="fresh_sha",
            )
        finally:
            for patcher in reversed(patches):
                patcher.stop()

        assert result.verdict == "error"
        assert result.note == browser_qa_freshness.SHA_MISMATCH

    def test_execute_scenario_reports_a_missing_record_as_its_own_reason(
        self, db_path: str
    ) -> None:
        """The scenario path must carry the reason, not relabel it.

        The helper-level tests above cannot catch a caller that hardcodes one
        note for every freshness outcome — that is exactly the defect this
        guards, and it lived here rather than in the helper. No ephemeral
        row is seeded, so a caller collapsing outcomes would report a SHA
        mismatch for a deployment nothing ever recorded.
        """
        _seed_item(db_path, 501)
        req_id = _seed_requirement(
            db_path, 501, "browser-check",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    _browser_verdict_assertion(),
                ],
            },
        )
        _ensure_ephemeral_table(db_path)

        # A project that publishes no identity proof: the scenario must
        # carry the missing-record reason through rather than relabelling
        # it. Pinned here because the resolver reads the control plane, and
        # this test is about the caller, not about that read.
        patches = _patch_external_deps(db_path) + [
            mock.patch(
                "yoke_core.domain.browser_qa_freshness."
                "resolve_preview_identity_target",
                return_value=preview_identity.PreviewIdentityTarget(
                    unconfigured=True
                ),
            )
        ]
        for patcher in patches:
            patcher.start()
        try:
            result = browser_qa.execute_scenario(
                item_id=501,
                project="testproj",
                requirement_id=req_id,
                base_url="http://localhost:9999",
                expected_branch="YOK-501",
                expected_sha="fresh_sha",
            )
        finally:
            for patcher in reversed(patches):
                patcher.stop()

        assert result.verdict == "error"
        assert result.note == browser_qa_freshness.DEPLOYMENT_RECORD_MISSING
        assert result.note != browser_qa_freshness.SHA_MISMATCH

    def test_execute_scenario_rejects_partial_freshness_inputs(self, db_path: str) -> None:
        """Polish: partial freshness args must fail closed instead of skipping validation."""
        _seed_item(db_path, 502)
        req_id = _seed_requirement(
            db_path, 502, "browser-check",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    _browser_verdict_assertion(),
                ],
            },
        )

        result = browser_qa.execute_scenario(
            item_id=502,
            project="testproj",
            requirement_id=req_id,
            base_url="http://localhost:9999",
            expected_branch="YOK-502",
        )

        assert result.verdict == "error"
        assert result.note == "freshness_args_incomplete"

    def test_execute_scenario_passes_without_freshness_args(self, db_path: str) -> None:
        """Backward compat: omitting expected_branch/sha skips freshness check."""
        _seed_item(db_path, 501)
        _seed_requirement(
            db_path, 501, "browser-check",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    _browser_verdict_assertion(),
                ],
            },
        )

        result = _run_scenario(
            db_path, 501,
            execute_step_responses=[{"success": True, "artifacts": []}],
        )
        assert result.verdict == "pass"

    def test_execute_scenario_records_code_identity_in_raw_result(
        self, tmp_path: Path, db_path: str
    ) -> None:
        """Browser QA runs persist the branch/SHA they executed against."""
        _seed_item(db_path, 503)
        req_id = _seed_requirement(
            db_path, 503, "browser-check",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    _browser_verdict_assertion(),
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
                requirement_id=req_id,
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
