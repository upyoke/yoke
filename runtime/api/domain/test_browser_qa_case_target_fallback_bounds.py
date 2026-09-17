"""Browser QA — asking the target itself is the last source, not a softer one.

The target a case browses can answer for itself, which closes the gap where
nothing was deployed and no preview proof is configured. The risk that
creates is the opposite one: a deployment that was explicitly bound and
failed could quietly become a local pass, because a host that is right
there will happily answer. These drive ``execute_scenario`` end to end to
show it does not — every source that had something to say still decides.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from yoke_core.domain import browser_qa
from yoke_core.domain import browser_qa_freshness_outcome as outcome
from yoke_core.domain import browser_qa_preview_identity as preview_identity
from yoke_core.domain import served_revision_probe as probe
from runtime.api.domain.browser_qa_ephemeral_fixtures import _placeholder
from yoke_core.domain.browser_qa_freshness_outcome import FreshnessFailure


SHA = "a" * 40
OTHER_SHA = "b" * 40
TARGET = "http://127.0.0.1:47311"


@pytest.fixture()
def db_path(tmp_path):
    from runtime.api.fixtures.file_test_db import init_test_db

    with init_test_db(tmp_path) as path:
        yield path


def _requirement(db_path: str, item: int, base_url: str) -> int:
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


def _run_scenario(
    db_path: str,
    item: int,
    *,
    preview: preview_identity.PreviewIdentityTarget,
    target_body: str = SHA,
    base_url: str = TARGET,
):
    """Drive the scenario, recording whether the target itself was asked."""
    return _run_with_requirement(
        db_path,
        item,
        _requirement(db_path, item, base_url),
        preview=preview,
        target_body=target_body,
        base_url=base_url,
    )


def _run_with_requirement(
    db_path: str,
    item: int,
    req_id: int,
    *,
    preview: preview_identity.PreviewIdentityTarget,
    target_body: str = SHA,
    base_url: str = TARGET,
):
    """The same drive, for a case whose requirement the caller already seeded."""
    from runtime.api.domain.browser_qa_test_helpers import _patch_external_deps

    asked_target: list[str] = []
    started: list = []

    def target_fetch(url: str) -> probe.ServedRevisionRead:
        asked_target.append(url)
        return probe.ServedRevisionRead(status=200, body=target_body)

    patches = _patch_external_deps(db_path) + [
        mock.patch(
            "yoke_core.domain.browser_qa_freshness."
            "resolve_preview_identity_target",
            return_value=preview,
        ),
        mock.patch(
            "yoke_core.domain.browser_qa_case_target_identity."
            "origin_bound_session_fetch",
            return_value=target_fetch,
        ),
        # Patched at the freshness module's own seam rather than on the
        # shared probe: both identity readers import the one probe module,
        # so patching it there would answer for the target too and the test
        # would stop testing which source decided.
        mock.patch(
            "yoke_core.domain.browser_qa_freshness.verify_preview_identity",
            return_value=FreshnessFailure(
                outcome.SHA_MISMATCH,
                f"The preview is serving {OTHER_SHA}, not {SHA}.",
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
    return result, asked_target, started


class TestTheFallbackIsReachedOnlyWhereNothingElseCanAnswer:

    def test_an_unconfigured_project_asks_the_target_itself(
        self, db_path: str
    ) -> None:
        result, asked, started = _run_scenario(
            db_path, 700,
            preview=preview_identity.PreviewIdentityTarget(unconfigured=True),
        )

        assert result.note != outcome.DEPLOYMENT_RECORD_MISSING
        assert asked, "the target must be the one asked when nothing else can"
        assert started, "a verified target is browsed"

    def test_a_configured_preview_that_answers_wrongly_still_refuses(
        self, db_path: str
    ) -> None:
        """The failure this prevents: a preview serving the wrong commit
        being overruled by a local server that serves the right one."""
        result, asked, started = _run_scenario(
            db_path, 701,
            preview=preview_identity.PreviewIdentityTarget(
                origin="https://branch-x.preview.example.test",
                path="/candidate-revision",
            ),
        )

        assert result.verdict == "error"
        assert result.note == outcome.SHA_MISMATCH
        assert asked == [], "a configured preview's failure is the answer"
        assert started == []

    def test_an_unreadable_identity_configuration_still_refuses(
        self, db_path: str
    ) -> None:
        """Could-not-ask is not the same as nothing-to-ask, so it must not
        open the fallback that absence opens."""
        result, asked, started = _run_scenario(
            db_path, 702,
            preview=preview_identity.PreviewIdentityTarget(
                unreadable="capability read failed: denied",
            ),
        )

        assert result.verdict == "error"
        assert result.note == outcome.IDENTITY_CONFIG_UNREADABLE
        assert asked == []
        assert started == []

    def test_a_target_serving_the_wrong_commit_refuses_rather_than_passes(
        self, db_path: str
    ) -> None:
        result, asked, started = _run_scenario(
            db_path, 703,
            preview=preview_identity.PreviewIdentityTarget(unconfigured=True),
            target_body=OTHER_SHA,
        )

        assert result.verdict == "error"
        assert result.note == outcome.SHA_MISMATCH
        assert asked, "the target was asked"
        assert started == [], "no browser starts against an unproven target"

    def test_evidence_may_not_be_collected_from_an_unasked_host(
        self, db_path: str
    ) -> None:
        """Freshness covers the host that answered. Browsing a different one
        under that claim is the binding this shares with every other source.

        The target answers about itself, so the two can only diverge when a
        redirect or a second host is involved; the check is kept because the
        claim it guards is identical.
        """
        result, _, started = _run_scenario(
            db_path, 704,
            preview=preview_identity.PreviewIdentityTarget(unconfigured=True),
            base_url="http://127.0.0.1:47311/app/inbox",
        )

        assert result.note != outcome.EXECUTION_TARGET_UNAUTHORIZED
        assert started, "a route under the answering origin is that origin"


class TestTheRecordedCommitIsEvidence:
    """A run records the commit a source produced, or records none at all.

    The merge gate reads this field to decide whether a verdict covers the
    commit being merged, so the failure this prevents is the whole point of
    the check: a run stamping the commit it was *asked* about would let a
    gate that trusts the field pass on the strength of the question.
    """

    def _recorded_identity(self, db_path: str, requirement_id: int):
        from runtime.api.fixtures.file_test_db import connect_test_db

        conn = connect_test_db(db_path)
        try:
            rows = conn.execute(
                "SELECT raw_result FROM qa_runs WHERE qa_requirement_id = "
                f"{_placeholder(conn)} ORDER BY id",
                (requirement_id,),
            ).fetchall()
        finally:
            conn.close()
        return [
            json.loads(row[0] or "{}").get("code_identity")
            for row in rows
            if row[0]
        ]

    def test_the_commit_recorded_is_the_one_the_target_served(
        self, db_path: str
    ) -> None:
        req_id = _requirement(db_path, 710, TARGET)
        _run_with_requirement(
            db_path, 710, req_id,
            preview=preview_identity.PreviewIdentityTarget(unconfigured=True),
            target_body=SHA,
        )

        identities = self._recorded_identity(db_path, req_id)
        assert identities, "the run recorded nothing to read"
        assert all(entry and entry.get("sha") == SHA for entry in identities)

    def test_a_run_with_no_verified_reading_records_no_commit(
        self, db_path: str
    ) -> None:
        """Freshness was never asked for, so nothing verified anything and
        the run must not carry a commit it could only have assumed."""
        from runtime.api.domain.browser_qa_test_helpers import (
            _patch_external_deps,
        )

        req_id = _requirement(db_path, 711, TARGET)
        patches = _patch_external_deps(db_path)
        for patcher in patches:
            patcher.start()
        try:
            browser_qa.execute_scenario(
                item_id=711,
                project="testproj",
                requirement_id=req_id,
                base_url=TARGET,
            )
        finally:
            for patcher in reversed(patches):
                patcher.stop()

        identities = self._recorded_identity(db_path, req_id)
        assert identities, "the run recorded nothing to read"
        assert all(not entry for entry in identities)
