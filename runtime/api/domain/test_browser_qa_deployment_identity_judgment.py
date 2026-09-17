"""Whether the deployment a run-bound Browser case names proves the candidate.

The judgment is present-tense on purpose. A persistent environment is mutable
and shared, so what a run deployed to it is not what it is serving once a
later run replaces that deployment, and only asking it now can tell them
apart.

Sibling to ``test_browser_qa_deployment_identity.py``, which covers the
server-side resolution these judge over. Split because the two are different
questions — which deployment, and what it is serving — and each grew its own
cases. The external answer is a fixture; nothing else here is.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import browser_qa_freshness_outcome as outcome
from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.browser_qa_deployment_identity import (
    DeploymentUnderTest,
    validate_deployment_identity,
)


DEPLOYED_SHA = "c" * 40
OTHER_SHA = "d" * 40
ENVIRONMENT = "prod"
ENVIRONMENT_URL = "https://app.example.test"
IDENTITY_PATH = "/candidate-revision"


def _fixture_fetch(body: str, *, status: int = 200, error: str = ""):
    return lambda _url: probe.ServedRevisionRead(
        status=status, body=body, error=error
    )


class TestIdentityJudgment:
    """Whether the resolved deployment proves the candidate under test."""

    def test_the_environment_may_answer_for_itself(self):
        failure = validate_deployment_identity(
            DEPLOYED_SHA,
            target=DeploymentUnderTest(
                environment=ENVIRONMENT,
                origin=ENVIRONMENT_URL,
                identity_path=IDENTITY_PATH,
            ),
            fetch=_fixture_fetch(DEPLOYED_SHA),
        )
        assert failure is None

    @pytest.mark.parametrize(
        "body,status,error,expected",
        [
            (OTHER_SHA, 200, "", outcome.SHA_MISMATCH),
            ("ok", 200, "", outcome.IDENTITY_PROOF_MALFORMED),
            ("", 0, "connection refused", outcome.IDENTITY_PROOF_UNAVAILABLE),
        ],
    )
    def test_a_live_answer_that_is_not_the_candidate_refuses(
        self, body, status, error, expected
    ):
        failure = validate_deployment_identity(
            DEPLOYED_SHA,
            target=DeploymentUnderTest(
                environment=ENVIRONMENT,
                origin=ENVIRONMENT_URL,
                identity_path=IDENTITY_PATH,
            ),
            fetch=_fixture_fetch(body, status=status, error=error),
        )
        assert failure is not None
        assert failure.reason == expected

    def test_an_environment_that_cannot_be_asked_names_what_is_missing(self):
        no_path = validate_deployment_identity(
            DEPLOYED_SHA,
            target=DeploymentUnderTest(
                environment=ENVIRONMENT, origin=ENVIRONMENT_URL
            ),
        )
        assert no_path is not None
        assert no_path.reason == outcome.DEPLOYMENT_RECORD_MISSING
        assert "identity_path" in no_path.message

        no_url = validate_deployment_identity(
            DEPLOYED_SHA,
            target=DeploymentUnderTest(
                environment=ENVIRONMENT, identity_path=IDENTITY_PATH
            ),
        )
        assert no_url is not None
        assert no_url.reason == outcome.DEPLOYMENT_RECORD_MISSING
        assert "no registered url" in no_url.message
        assert (
            "yoke projects environment update --project <project> "
            "--environment prod --url"
        ) in no_url.message

    def test_unreadable_configuration_is_not_reported_as_unconfigured(self):
        failure = validate_deployment_identity(
            DEPLOYED_SHA,
            target=DeploymentUnderTest(
                environment=ENVIRONMENT,
                origin=ENVIRONMENT_URL,
                identity_error="the capability could not be read (denied)",
            ),
        )
        assert failure is not None
        assert failure.reason == outcome.IDENTITY_CONFIG_UNREADABLE

    def test_an_unresolved_run_refuses_with_its_own_reason(self):
        failure = validate_deployment_identity(
            DEPLOYED_SHA,
            target=DeploymentUnderTest(unresolved="run names no deployment"),
        )
        assert failure is not None
        assert failure.reason == outcome.DEPLOYMENT_TARGET_UNRESOLVED

    def test_a_later_release_to_the_same_environment_refuses(self):
        """Run A deployed A; run B has since replaced it; A's QA must refuse.

        The environment is shared and mutable, so the reading is what it
        serves now, not what run A once delivered to it. Browsing B while
        stamping the evidence A is the substitution this refuses.
        """
        failure = validate_deployment_identity(
            DEPLOYED_SHA,
            target=DeploymentUnderTest(
                environment=ENVIRONMENT,
                origin=ENVIRONMENT_URL,
                identity_path=IDENTITY_PATH,
            ),
            fetch=_fixture_fetch(OTHER_SHA),
        )
        assert failure is not None
        assert failure.reason == outcome.SHA_MISMATCH
        assert OTHER_SHA in failure.message

    def test_the_environment_is_asked_on_every_call(self):
        """No stored answer stands in for the reading, so none can go stale."""
        asked: list[str] = []

        def _record(url: str):
            asked.append(url)
            return probe.ServedRevisionRead(status=200, body=DEPLOYED_SHA)

        target = DeploymentUnderTest(
            environment=ENVIRONMENT,
            origin=ENVIRONMENT_URL,
            identity_path=IDENTITY_PATH,
        )
        assert validate_deployment_identity(
            DEPLOYED_SHA, target=target, fetch=_record,
        ) is None
        assert validate_deployment_identity(
            DEPLOYED_SHA, target=target, fetch=_record,
        ) is None
        assert asked == [
            f"{ENVIRONMENT_URL}{IDENTITY_PATH}",
            f"{ENVIRONMENT_URL}{IDENTITY_PATH}",
        ]
