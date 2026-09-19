"""A deployment-run Browser case is bound to what that run shipped.

The standalone case path took a branch and a commit on the command line and
proved the target was serving them. The deployment stage — the path that
certifies production — supplied neither, so its captures were recorded with
no code identity and ``freshness_validated`` false: evidence about no
particular build. The run has always recorded the commit it was pinned to
deliver; these cover it being asked, and the refusals when it cannot answer.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from yoke_core.domain import browser_qa
from yoke_core.domain.browser_qa_run_source import run_bound_identity
from runtime.api.domain.browser_qa_ephemeral_fixtures import (
    seed_deployment_run,
)
from runtime.api.domain.browser_qa_test_helpers import (
    _browser_check_steps,
    _patch_external_deps,
    _placeholder,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


RUN_ID = "run-20260101-001"
PINNED_SHA = "4f2b1c0d9e8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c"


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        yield path


def _seed_run_requirement(db_path: str, run_id: str) -> int:
    """Attach one Browser case to a deployment run rather than an item."""
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    cur = conn.execute(
        f"""
        INSERT INTO qa_requirements (
            deployment_run_id, qa_kind, method_id, method_config, qa_phase,
            target_env, blocking_mode, requirement_source, created_at
        ) VALUES ({p}, 'plan_case', 'browser-check', {p}, 'verification',
                  'persistent', 'blocking', 'seeded_default', {p})
        RETURNING id
        """,
        (
            run_id,
            json.dumps(
                {
                    "base_url": "http://localhost:9999",
                    "steps": _browser_check_steps(),
                }
            ),
            "2026-01-01T00:00:00Z",
        ),
    )
    req_id = int(cur.fetchone()[0])
    conn.commit()
    conn.close()
    return req_id


def _run_deployment_case(db_path: str, req_id: str | int, **patch_kwargs):
    patches = _patch_external_deps(
        db_path,
        execute_step_responses=[{"success": True, "artifacts": []}],
        **patch_kwargs,
    )
    for patcher in patches:
        patcher.start()
    try:
        return browser_qa.execute_scenario(
            project="testproj",
            requirement_id=int(req_id),
            deployment_run_id=RUN_ID,
            base_url="http://localhost:9999",
        )
    finally:
        for patcher in reversed(patches):
            patcher.stop()


class TestRunBoundIdentityResolution:
    def test_pinned_commit_is_taken_from_the_run(self) -> None:
        failure, branch, sha = run_bound_identity(
            RUN_ID,
            {"run_source": {"sha": PINNED_SHA, "branch": "main"}},
            expected_branch=None,
            expected_sha=None,
        )
        assert failure is None
        assert (branch, sha) == ("main", PINNED_SHA)

    def test_unpinned_run_refuses_by_name(self) -> None:
        failure, _, _ = run_bound_identity(
            RUN_ID,
            {"run_source": {"sha": "", "branch": "main"}},
            expected_branch=None,
            expected_sha=None,
        )
        assert failure is not None
        assert failure.reason == "deployment_source_unpinned"
        assert "pinned to deliver" in failure.message

    def test_a_contradicting_commit_refuses_rather_than_choosing(self) -> None:
        failure, _, _ = run_bound_identity(
            RUN_ID,
            {"run_source": {"sha": PINNED_SHA, "branch": "main"}},
            expected_branch="main",
            expected_sha="0" * 40,
        )
        assert failure is not None
        assert failure.reason == "deployment_source_contradicted"
        assert PINNED_SHA in failure.message

    def test_an_agreeing_commit_is_accepted(self) -> None:
        failure, branch, sha = run_bound_identity(
            RUN_ID,
            {"run_source": {"sha": PINNED_SHA, "branch": "main"}},
            expected_branch="release",
            expected_sha=PINNED_SHA,
        )
        assert failure is None
        assert (branch, sha) == ("release", PINNED_SHA)


class TestDeploymentStageBindsItsEvidence:
    def test_run_case_proves_and_records_the_run_commit(
        self, db_path: str
    ) -> None:
        seed_deployment_run(db_path, RUN_ID, release_lineage=PINNED_SHA)
        req_id = _seed_run_requirement(db_path, RUN_ID)
        proved: list[tuple] = []

        def _establish(project, branch, sha, *, context, base_url="", **_kw):
            proved.append((branch, sha))
            return None, "http://localhost:9999", sha

        with mock.patch.object(
            browser_qa, "_establish_deployment_freshness", side_effect=_establish
        ):
            result = _run_deployment_case(db_path, req_id)

        assert result.verdict == "pass"
        # The stage supplied no expectation; the run's own commit was proved.
        assert proved == [("main", PINNED_SHA)]
        assert result.runs[0].code_identity == {
            "branch": "main",
            "sha": PINNED_SHA,
        }

        conn = connect_test_db(db_path)
        p = _placeholder(conn)
        row = conn.execute(
            f"SELECT raw_result FROM qa_runs WHERE qa_requirement_id = {p} "
            "ORDER BY id DESC LIMIT 1",
            (req_id,),
        ).fetchone()
        conn.close()
        payload = json.loads(row[0])
        assert payload["code_identity"] == {"branch": "main", "sha": PINNED_SHA}
        assert payload["freshness_validated"] is True

    def test_unpinned_run_refuses_before_any_browser_starts(
        self, db_path: str
    ) -> None:
        seed_deployment_run(db_path, RUN_ID, release_lineage="")
        req_id = _seed_run_requirement(db_path, RUN_ID)
        opened: list[dict] = []

        result = _run_deployment_case(db_path, req_id, opened_pages=opened)

        assert result.verdict == "error"
        assert result.note == "deployment_source_unpinned"
        assert opened == []

    def test_an_unprovable_environment_refuses(self, db_path: str) -> None:
        from yoke_core.domain.browser_qa_freshness_outcome import (
            FreshnessFailure,
        )

        seed_deployment_run(db_path, RUN_ID, release_lineage=PINNED_SHA)
        req_id = _seed_run_requirement(db_path, RUN_ID)

        with mock.patch.object(
            browser_qa,
            "_establish_deployment_freshness",
            return_value=(
                FreshnessFailure(
                    "identity_proof_unavailable", "the environment did not answer"
                ),
                "",
                "",
            ),
        ):
            result = _run_deployment_case(db_path, req_id)

        assert result.verdict == "error"
        assert result.note == "identity_proof_unavailable"
