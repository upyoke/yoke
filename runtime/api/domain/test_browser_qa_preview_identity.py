"""Browser QA — proving freshness from what a project's preview serves.

These cover the path taken when nothing recorded a deployment at all. Two
properties matter more than the happy case: the answer is sought only where
the project's own configuration says its preview lives, and "we could not
read that configuration" never reads as "the project configured none".
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain import browser_qa
from yoke_core.domain import browser_qa_freshness_outcome as outcome
from yoke_core.domain import browser_qa_preview_identity as preview_identity
from yoke_core.domain import served_revision_probe as probe


SHA = "a" * 40
OTHER_SHA = "b" * 40


def _target(origin: str = "https://branch-x.preview.example.test") -> object:
    return preview_identity.PreviewIdentityTarget(
        origin=origin, path="/candidate-revision"
    )


class TestPreviewIdentityProof:
    """The project's own preview as a substitute for an absent record."""

    def test_served_revision_satisfies_a_missing_record(self) -> None:
        """A provider that records nothing can still prove what it serves."""
        with mock.patch("yoke_core.domain.browser_qa._log") as mock_log:
            err = browser_qa._validate_deployed_sha(
                "testproj", "branch-x", SHA,
                deployed_sha=None, deployment_recorded=False,
                identity_target=_target(),
                fetch_identity=lambda url: probe.ServedRevisionRead(
                    status=200, body=f"{SHA}\n"
                ),
            )
        assert err is None
        logged = mock_log.call_args[0][0]
        # The log names the evidence source: a live answer is not a stored
        # record, and a reader has to be able to tell them apart.
        assert "revision served at" in logged
        assert "https://branch-x.preview.example.test/candidate-revision" in logged

    def test_the_probed_host_comes_from_project_policy_not_the_caller(self) -> None:
        """A caller-named target cannot supply the answer.

        The origin is derived from the project's own ephemeral-env policy and
        the branch under test. Were it taken from a URL passed to the check,
        any host serving a matching SHA would satisfy freshness for any
        project — so this asserts the URL actually fetched.
        """
        asked: list[str] = []

        def _fetch(url: str) -> probe.ServedRevisionRead:
            asked.append(url)
            return probe.ServedRevisionRead(status=200, body=SHA)

        err = browser_qa._validate_deployed_sha(
            "testproj", "branch-x", SHA,
            deployed_sha=None, deployment_recorded=False,
            identity_target=_target(),
            fetch_identity=_fetch,
        )
        assert err is None
        assert asked == ["https://branch-x.preview.example.test/candidate-revision"]

    def test_a_foreign_host_serving_the_same_sha_is_never_consulted(self) -> None:
        """The resolver, not the caller, decides who may answer."""
        resolved = preview_identity.PreviewIdentityTarget(
            origin="https://branch-x.preview.example.test",
            path="/candidate-revision",
        )
        asked: list[str] = []

        def _fetch(url: str) -> probe.ServedRevisionRead:
            asked.append(url)
            return probe.ServedRevisionRead(status=200, body=SHA)

        browser_qa._validate_deployed_sha(
            "testproj", "branch-x", SHA,
            deployed_sha=None, deployment_recorded=False,
            identity_target=resolved,
            fetch_identity=_fetch,
        )
        assert all("attacker.example.test" not in url for url in asked)
        assert asked and asked[0].startswith(
            "https://branch-x.preview.example.test/"
        )

    def test_unreadable_configuration_is_not_reported_as_unconfigured(self) -> None:
        """Denied or broken config is unverified, not a declined option."""
        err = browser_qa._validate_deployed_sha(
            "testproj", "branch-x", SHA,
            deployed_sha=None, deployment_recorded=False,
            identity_target=preview_identity.PreviewIdentityTarget(
                unreadable="capability read failed: permission denied"
            ),
        )
        assert err is not None
        assert err.reason == outcome.IDENTITY_CONFIG_UNREADABLE
        assert err.reason != outcome.DEPLOYMENT_RECORD_MISSING
        assert "permission denied" in err.message
        assert "unverified, not" in err.message

    def test_unconfigured_project_does_not_advise_a_redeploy_as_the_fix(self) -> None:
        """Recovery text must fit the provider that produced the state."""
        err = browser_qa._validate_deployed_sha(
            "testproj", "branch-x", SHA,
            deployed_sha=None, deployment_recorded=False,
            identity_target=preview_identity.PreviewIdentityTarget(
                unconfigured=True
            ),
        )
        assert err is not None
        assert err.reason == outcome.DEPLOYMENT_RECORD_MISSING
        assert "configures no identity_path" in err.message
        assert "capability-settings merge" in err.message

    def test_a_recorded_mismatch_refuses_without_asking_the_network(self) -> None:
        """The proof substitutes for an absent record, never a present one."""
        probed: list[str] = []

        def _fetch(url: str) -> probe.ServedRevisionRead:
            probed.append(url)
            return probe.ServedRevisionRead(status=200, body=OTHER_SHA)

        err = browser_qa._validate_deployed_sha(
            "testproj", "branch-x", OTHER_SHA,
            deployed_sha="c" * 40, deployment_recorded=True,
            identity_target=_target(),
            fetch_identity=_fetch,
        )
        assert err is not None
        assert err.reason == outcome.SHA_MISMATCH
        assert probed == [], "a recorded mismatch must refuse without probing"

    @pytest.mark.parametrize(
        "read,expected_reason",
        [
            (
                probe.ServedRevisionRead(error="connection refused"),
                outcome.IDENTITY_PROOF_UNAVAILABLE,
            ),
            (
                probe.ServedRevisionRead(status=404, error="HTTP 404"),
                outcome.IDENTITY_PROOF_UNAVAILABLE,
            ),
            (
                probe.ServedRevisionRead(status=200, body=SHA[:12]),
                outcome.IDENTITY_PROOF_MALFORMED,
            ),
            (
                probe.ServedRevisionRead(status=200, body="<!doctype html><html>"),
                outcome.IDENTITY_PROOF_MALFORMED,
            ),
            (
                probe.ServedRevisionRead(status=200, body=OTHER_SHA),
                outcome.SHA_MISMATCH,
            ),
        ],
    )
    def test_each_unproven_answer_reports_its_own_reason(
        self, read, expected_reason: str
    ) -> None:
        """Unverifiable, malformed, and wrong are three different answers."""
        err = browser_qa._validate_deployed_sha(
            "testproj", "branch-x", SHA,
            deployed_sha=None, deployment_recorded=False,
            identity_target=_target(),
            fetch_identity=lambda url: read,
        )
        assert err is not None
        assert err.reason == expected_reason


class TestIdentityPathIsRefusedWhereItIsSet:
    """Confinement is enforced at the write, not only at the read.

    Both settings write paths — ``cmd_capability_set_settings`` and the
    merge loop's ``cas_write`` — call ``canonicalize_capability_settings``
    before anything reaches the database, and its ``ephemeral-env`` branch
    builds the typed policy. So this is the function that stands between an
    operator and a stored value that would send the probe off-origin,
    whether the write arrived through the CLI or the relayed handler.
    """

    @pytest.mark.parametrize(
        "escaping",
        [
            "https://elsewhere.example.test/candidate-revision",
            "//elsewhere.example.test/candidate-revision",
            "\\\\elsewhere.example.test",
            "candidate-revision",
        ],
    )
    def test_a_value_leaving_the_origin_is_refused_at_canonicalization(
        self, escaping: str
    ) -> None:
        from yoke_core.domain.projects_capability_settings_validation import (
            canonicalize_capability_settings,
        )
        import json as _json

        payload = _json.dumps(
            {
                "trigger": "github-push",
                "preview_domain": "preview.example.test",
                "identity_path": escaping,
            }
        )
        with pytest.raises(ValueError, match="leaves the preview"):
            canonicalize_capability_settings("ephemeral-env", payload)

    def test_an_origin_relative_value_is_accepted_and_stored(self) -> None:
        from yoke_core.domain.projects_capability_settings_validation import (
            canonicalize_capability_settings,
        )
        import json as _json

        stored = canonicalize_capability_settings(
            "ephemeral-env",
            _json.dumps(
                {
                    "trigger": "github-push",
                    "preview_domain": "preview.example.test",
                    "identity_path": "/candidate-revision",
                }
            ),
        )
        assert _json.loads(stored)["identity_path"] == "/candidate-revision"
