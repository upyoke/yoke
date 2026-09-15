"""Browser QA — proving freshness from what a deployment serves.

These cover the path taken when nothing recorded a deployment at all: the
project's configured identity path lets the deployment answer for itself.
The record-based comparisons live beside them in
``test_outcome.py``; what is specific here is that a live
answer is evidence of a different kind, with its own failure modes — an
endpoint that cannot answer, one that answers with a page instead of a
commit, and one that answers honestly with a different commit.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import browser_qa
from yoke_core.domain import browser_qa_freshness_outcome as outcome
from yoke_core.domain import browser_qa_served_identity as served_identity
from unittest import mock


class TestServedIdentityProof:
    """The configured identity path as a substitute for an absent record."""

    def test_served_identity_satisfies_a_missing_record(self) -> None:
        """A provider that records nothing can still prove what it serves."""
        sha = "a" * 40
        read = served_identity.IdentityRead(status=200, body=f"{sha}\n")
        with mock.patch("yoke_core.domain.browser_qa._log") as mock_log:
            err = browser_qa._validate_deployed_sha(
                "testproj", "branch-x", sha,
                deployed_sha=None, deployment_recorded=False,
                base_url="https://preview.example.test/",
                identity_path="/candidate-revision",
                fetch_identity=lambda url: read,
            )
        assert err is None
        # The log must name the evidence source: a live answer is not a
        # stored record, and a reader has to be able to tell them apart.
        logged = mock_log.call_args[0][0]
        assert "served identity" in logged
        assert "https://preview.example.test/candidate-revision" in logged

    def test_served_identity_never_overrides_a_recorded_mismatch(self) -> None:
        """The proof substitutes for an absent record, never for a present one."""
        probed: list = []

        def _fetch(url: str):
            probed.append(url)
            return served_identity.IdentityRead(status=200, body="b" * 40)

        err = browser_qa._validate_deployed_sha(
            "testproj", "branch-x", "b" * 40,
            deployed_sha="c" * 40, deployment_recorded=True,
            base_url="https://preview.example.test",
            identity_path="/candidate-revision",
            fetch_identity=_fetch,
        )
        assert err is not None
        assert err.reason == outcome.SHA_MISMATCH
        assert probed == [], "a recorded mismatch must refuse without probing"

    def test_unreachable_identity_is_unverified_not_stale(self) -> None:
        """An endpoint that cannot answer proves nothing either way."""
        read = served_identity.IdentityRead(error="connection refused")
        err = browser_qa._validate_deployed_sha(
            "testproj", "branch-x", "a" * 40,
            deployed_sha=None, deployment_recorded=False,
            base_url="https://preview.example.test",
            identity_path="/candidate-revision",
            fetch_identity=lambda url: read,
        )
        assert err is not None
        assert err.reason == outcome.IDENTITY_PROOF_UNAVAILABLE
        assert err.reason != outcome.SHA_MISMATCH
        assert "connection refused" in err.message

    def test_non_200_identity_is_unavailable(self) -> None:
        """A 404 on the identity path is an unanswered question, not a pass."""
        read = served_identity.IdentityRead(status=404, error="HTTP 404")
        err = browser_qa._validate_deployed_sha(
            "testproj", "branch-x", "a" * 40,
            deployed_sha=None, deployment_recorded=False,
            base_url="https://preview.example.test",
            identity_path="/candidate-revision",
            fetch_identity=lambda url: read,
        )
        assert err is not None
        assert err.reason == outcome.IDENTITY_PROOF_UNAVAILABLE

    def test_abbreviated_identity_is_malformed_not_a_match(self) -> None:
        """A prefix of the expected SHA is not proof of the expected SHA."""
        sha = "a" * 40
        read = served_identity.IdentityRead(status=200, body=sha[:12])
        err = browser_qa._validate_deployed_sha(
            "testproj", "branch-x", sha,
            deployed_sha=None, deployment_recorded=False,
            base_url="https://preview.example.test",
            identity_path="/candidate-revision",
            fetch_identity=lambda url: read,
        )
        assert err is not None
        assert err.reason == outcome.IDENTITY_PROOF_MALFORMED

    def test_html_identity_response_is_malformed(self) -> None:
        """A routed-to-the-app page is not an identity answer."""
        read = served_identity.IdentityRead(
            status=200, body="<!doctype html><html><body>Take the Helm</body></html>"
        )
        err = browser_qa._validate_deployed_sha(
            "testproj", "branch-x", "a" * 40,
            deployed_sha=None, deployment_recorded=False,
            base_url="https://preview.example.test",
            identity_path="/candidate-revision",
            fetch_identity=lambda url: read,
        )
        assert err is not None
        assert err.reason == outcome.IDENTITY_PROOF_MALFORMED

    def test_served_identity_mismatch_names_the_live_source(self) -> None:
        """A live disagreement is a mismatch, described as what it is."""
        err = browser_qa._validate_deployed_sha(
            "testproj", "branch-x", "a" * 40,
            deployed_sha=None, deployment_recorded=False,
            base_url="https://preview.example.test",
            identity_path="/candidate-revision",
            fetch_identity=lambda url: served_identity.IdentityRead(
                status=200, body="d" * 40
            ),
        )
        assert err is not None
        assert err.reason == outcome.SHA_MISMATCH
        assert "reported about itself" in err.message
        assert "stored record" in err.message

    def test_unconfigured_identity_does_not_advise_a_redeploy_as_the_fix(
        self,
    ) -> None:
        """Recovery text must fit the provider that produced the state.

        A provider that never writes records is not fixed by redeploying, so
        the message leads with configuring the proof and offers the recording
        provider as the alternative rather than the other way round.
        """
        err = browser_qa._validate_deployed_sha(
            "testproj", "branch-x", "a" * 40,
            deployed_sha=None, deployment_recorded=False,
            base_url="https://preview.example.test",
            identity_path="",
        )
        assert err is not None
        assert err.reason == outcome.DEPLOYMENT_RECORD_MISSING
        assert "configures no identity_path" in err.message
        assert "capability-settings merge" in err.message

    def test_identity_path_leaving_the_origin_is_refused_at_configuration(
        self,
    ) -> None:
        """The origin is the authorized target; the setting picks a path."""
        from yoke_core.domain.ephemeral_substrate import (
            EphemeralPolicyError,
            ephemeral_policy_from_capability,
        )

        for escaping in (
            "https://elsewhere.example.test/candidate-revision",
            "//elsewhere.example.test/candidate-revision",
            "\\elsewhere.example.test",
        ):
            with pytest.raises(EphemeralPolicyError, match="leaves the preview"):
                ephemeral_policy_from_capability(
                    "testproj",
                    {
                        "trigger": "github-push",
                        "preview_domain": "preview.example.test",
                        "identity_path": escaping,
                    },
                )
