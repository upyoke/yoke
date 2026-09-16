"""Browser QA — the run may only browse what proved its freshness.

Separate from the identity-proof tests because the gap these guard lives
*between* the proof and the execution: freshness can be proved against the
project's authorized preview while the run is pointed somewhere else, and
the evidence would still be labelled fresh. These drive
``execute_scenario`` end to end for that reason.
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain import browser_qa
from yoke_core.domain import browser_qa_freshness_outcome as outcome
from yoke_core.domain import browser_qa_preview_identity as preview_identity
from yoke_core.domain import served_revision_probe as probe


SHA = "a" * 40


class TestExecutionTargetBinding:
    """A proof covers the deployment that answered it — and nothing else.

    These drive ``execute_scenario``, not the comparison helper, because the
    gap being guarded is between the two: freshness can be proved against
    the project's authorized preview while the run browses somewhere else
    entirely, which would attach "serving the expected commit" to evidence
    from a host nothing was asked about.
    """

    @pytest.fixture
    def db_path(self, tmp_path):
        from runtime.api.fixtures.file_test_db import init_test_db

        with init_test_db(tmp_path) as path:
            yield path

    def _requirement(self, db_path: str, item: int, base_url: str) -> int:
        from runtime.api.domain.browser_qa_test_helpers import (
            _browser_verdict_assertion,
            _seed_item,
            _seed_requirement,
        )

        _seed_item(db_path, item)
        return _seed_requirement(
            db_path, item, "browser-check",
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "route": "/"},
                    _browser_verdict_assertion(),
                ],
            },
        )

    def _run(self, db_path: str, item: int, *, base_url: str, origin: str):
        """Run the scenario with the preview proving the expected commit."""
        from runtime.api.domain.browser_qa_test_helpers import (
            _patch_external_deps,
        )

        req_id = self._requirement(db_path, item, base_url)
        started: list = []
        patches = _patch_external_deps(db_path) + [
            mock.patch(
                "yoke_core.domain.browser_qa_freshness."
                "resolve_preview_identity_target",
                return_value=preview_identity.PreviewIdentityTarget(
                    origin=origin, path="/candidate-revision"
                ),
            ),
            mock.patch(
                "yoke_core.domain.browser_qa_preview_identity.probe."
                "probe_served_revision",
                side_effect=lambda origin_arg, path, **kw: probe.ProbeOutcome(
                    f"{origin_arg}{path}", served=SHA
                ),
            ),
            mock.patch.object(
                browser_qa, "_ensure_daemon_running",
                side_effect=lambda **kw: started.append(kw) or None,
            ),
        ]
        for patcher in patches:
            patcher.start()
        try:
            result = browser_qa.execute_scenario(
                item_id=item,
                project="testproj",
                requirement_id=req_id,
                base_url=base_url,
                expected_branch="branch-x",
                expected_sha=SHA,
            )
        finally:
            for patcher in reversed(patches):
                patcher.stop()
        return result, started

    def test_a_foreign_target_is_refused_before_any_browsing(
        self, db_path: str
    ) -> None:
        """Proof from the authorized preview cannot vouch for another host."""
        result, started = self._run(
            db_path, 620,
            base_url="https://foreign.example.test",
            origin="https://branch-x.preview.example.test",
        )
        assert result.verdict == "error"
        assert result.note == outcome.EXECUTION_TARGET_UNAUTHORIZED
        assert started == [], "no browser may start for an unproven target"
        # No run executed, so nothing was recorded to carry the claim.
        assert result.executed == 0
        assert result.runs == []

    def test_the_proven_target_proceeds(self, db_path: str) -> None:
        """The deployment that answered is exactly the one we may browse."""
        result, started = self._run(
            db_path, 621,
            base_url="https://branch-x.preview.example.test",
            origin="https://branch-x.preview.example.test",
        )
        assert result.note != outcome.EXECUTION_TARGET_UNAUTHORIZED
        assert started, "the proven target must still be browsed"

    def test_a_route_under_the_proven_origin_is_allowed(
        self, db_path: str
    ) -> None:
        """Binding is per origin, not per URL: routes under it are the same
        deployment, and refusing them would break ordinary QA targets."""
        result, started = self._run(
            db_path, 622,
            base_url="https://branch-x.preview.example.test/app/dashboard",
            origin="https://branch-x.preview.example.test",
        )
        assert result.note != outcome.EXECUTION_TARGET_UNAUTHORIZED
        assert started, "a route under the proven origin is the proven target"


class TestRecordedDeploymentBinding:
    """The same invariant where a recorded deployment established freshness.

    A recorded row proves a deployment happened and what commit it carried;
    it says nothing about some other host. So the run is bound to the URL
    that row recorded, through the same check the proof path uses — one
    invariant, one implementation.
    """

    @pytest.fixture
    def db_path(self, tmp_path):
        from runtime.api.fixtures.file_test_db import init_test_db

        with init_test_db(tmp_path) as path:
            yield path

    def _run(self, db_path: str, item: int, *, base_url: str, recorded_url: str):
        from runtime.api.domain.browser_qa_test_helpers import (
            _browser_verdict_assertion,
            _patch_external_deps,
            _seed_item,
            _seed_requirement,
        )
        from runtime.api.domain.browser_qa_ephemeral_fixtures import (
            seed_ephemeral_env,
        )

        _seed_item(db_path, item)
        req_id = _seed_requirement(
            db_path, item, "browser-check",
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "route": "/"},
                    _browser_verdict_assertion(),
                ],
            },
        )
        seed_ephemeral_env(
            db_path, "testproj", "branch-rec",
            deployed_sha=SHA, url=recorded_url,
        )
        started: list = []
        patches = _patch_external_deps(db_path) + [
            mock.patch.object(
                browser_qa, "_ensure_daemon_running",
                side_effect=lambda **kw: started.append(kw) or None,
            ),
        ]
        for patcher in patches:
            patcher.start()
        try:
            result = browser_qa.execute_scenario(
                item_id=item,
                project="testproj",
                requirement_id=req_id,
                base_url=base_url,
                expected_branch="branch-rec",
                expected_sha=SHA,
            )
        finally:
            for patcher in reversed(patches):
                patcher.stop()
        return result, started

    def test_a_foreign_target_is_refused_before_any_browsing(
        self, db_path: str
    ) -> None:
        """A matching recorded SHA does not vouch for a different host."""
        result, started = self._run(
            db_path, 630,
            base_url="https://foreign.example.test",
            recorded_url="https://branch-rec.preview.example.test",
        )
        assert result.verdict == "error"
        assert result.note == outcome.EXECUTION_TARGET_UNAUTHORIZED
        assert started == [], "no browser may start for an unverified target"
        assert result.executed == 0
        assert result.runs == []

    def test_a_route_under_the_recorded_origin_succeeds(
        self, db_path: str
    ) -> None:
        """Routes under the recorded deployment are that same deployment."""
        result, started = self._run(
            db_path, 631,
            base_url="https://branch-rec.preview.example.test/app",
            recorded_url="https://branch-rec.preview.example.test",
        )
        assert result.note != outcome.EXECUTION_TARGET_UNAUTHORIZED
        assert started, "the recorded target must still be browsed"
