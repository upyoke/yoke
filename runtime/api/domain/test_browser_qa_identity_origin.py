"""Which base answers for the code a Browser case is looking at.

One host can front more than one deployed artifact. These cover the rule
that keeps them apart: the base a target names for its API answers for the
code, the base a browser visits answers only for itself, and a reply that
states no full commit SHA is refused whichever base produced it.
"""

from __future__ import annotations

import json
import unittest

from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.browser_qa_deployment_identity import (
    DeploymentUnderTest,
    validate_deployment_identity,
)
from yoke_core.domain.browser_qa_freshness_outcome import (
    IDENTITY_PROOF_MALFORMED,
    SHA_MISMATCH,
)

SERVED = "4a269c5656ea75622f6ccad6c6f8d9f9028acae5"
OTHER = "1bddf1e5ea07d80b8c0f535e44a324572c78aaed"

BROWSER_ORIGIN = "https://app.upyoke.com"
API_ORIGIN = "https://app.upyoke.com/api/orgs/upyoke"
IDENTITY_PATH = "/v1/health"

#: What the app shell in front of the deployment answers at the same path.
FRONTING_SERVICE_REPLY = json.dumps({"ok": True, "service": "platform-webapp"})


def _health(build: str) -> str:
    return json.dumps(
        {
            "status": "ok",
            "version": "v1",
            "engine_version": "0.1.1+launch.448",
            "build": build,
            "schema_ready": True,
        }
    )


class _Origin:
    """Answers one URL and records every URL it was asked for."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def __call__(self, url: str) -> probe.ServedRevisionRead:
        self.asked.append(url)
        if url not in self.answers:
            return probe.ServedRevisionRead(status=404, error="HTTP 404")
        return probe.ServedRevisionRead(status=200, body=self.answers[url])


def _fronted_target() -> DeploymentUnderTest:
    return DeploymentUnderTest(
        environment="prod",
        origin=BROWSER_ORIGIN,
        identity_origin=API_ORIGIN,
        identity_path=IDENTITY_PATH,
    )


def _single_origin_target(origin: str, path: str) -> DeploymentUnderTest:
    return DeploymentUnderTest(environment="prod", origin=origin, identity_path=path)


class TestIdentityOriginSelection(unittest.TestCase):
    def test_the_api_base_keeps_its_own_path_when_asked(self):
        """The prefix under which this artifact is reached must survive."""
        fetch = _Origin({f"{API_ORIGIN}{IDENTITY_PATH}": _health(SERVED)})

        failure = validate_deployment_identity(
            SERVED, target=_fronted_target(), fetch=fetch
        )

        self.assertIsNone(failure)
        self.assertEqual(fetch.asked, [f"{API_ORIGIN}{IDENTITY_PATH}"])

    def test_the_fronting_service_is_never_asked_for_this_answer(self):
        """The browser origin serves the same path and a different artifact."""
        fetch = _Origin(
            {
                f"{BROWSER_ORIGIN}{IDENTITY_PATH}": FRONTING_SERVICE_REPLY,
                f"{API_ORIGIN}{IDENTITY_PATH}": _health(SERVED),
            }
        )

        failure = validate_deployment_identity(
            SERVED, target=_fronted_target(), fetch=fetch
        )

        self.assertIsNone(failure)
        self.assertNotIn(f"{BROWSER_ORIGIN}{IDENTITY_PATH}", fetch.asked)

    def test_the_fronting_service_reply_would_not_have_proved_anything(self):
        """Asking the wrong base is a refusal, not a pass."""
        fetch = _Origin({f"{BROWSER_ORIGIN}{IDENTITY_PATH}": FRONTING_SERVICE_REPLY})
        wrong_base = _single_origin_target(BROWSER_ORIGIN, IDENTITY_PATH)

        failure = validate_deployment_identity(SERVED, target=wrong_base, fetch=fetch)

        assert failure is not None
        self.assertEqual(failure.reason, IDENTITY_PROOF_MALFORMED)
        self.assertIn("platform-webapp", failure.message)

    def test_a_target_naming_one_base_is_read_exactly_as_before(self):
        """A project whose host serves only its own deployment is unchanged."""
        origin = "https://buzzabuzz.com"
        fetch = _Origin({f"{origin}/candidate-revision": SERVED})

        failure = validate_deployment_identity(
            SERVED,
            target=_single_origin_target(origin, "/candidate-revision"),
            fetch=fetch,
        )

        self.assertIsNone(failure)
        self.assertEqual(fetch.asked, [f"{origin}/candidate-revision"])

    def test_a_configured_origin_still_cannot_smuggle_a_path(self):
        """The reduction rule stays in force for bases a person configures."""
        fetch = _Origin({f"{BROWSER_ORIGIN}/candidate-revision": SERVED})

        failure = validate_deployment_identity(
            SERVED,
            target=_single_origin_target(API_ORIGIN, "/candidate-revision"),
            fetch=fetch,
        )

        self.assertIsNone(failure)
        self.assertEqual(fetch.asked, [f"{BROWSER_ORIGIN}/candidate-revision"])


class TestHealthDocumentRevision(unittest.TestCase):
    def test_a_health_document_naming_another_build_is_a_mismatch(self):
        fetch = _Origin({f"{API_ORIGIN}{IDENTITY_PATH}": _health(OTHER)})

        failure = validate_deployment_identity(
            SERVED, target=_fronted_target(), fetch=fetch
        )

        assert failure is not None
        self.assertEqual(failure.reason, SHA_MISMATCH)
        self.assertIn(OTHER, failure.message)

    def test_an_unparseable_document_proves_nothing(self):
        truncated = _health(SERVED)[:40]
        fetch = _Origin({f"{API_ORIGIN}{IDENTITY_PATH}": truncated})

        failure = validate_deployment_identity(
            SERVED, target=_fronted_target(), fetch=fetch
        )

        assert failure is not None
        self.assertEqual(failure.reason, IDENTITY_PROOF_MALFORMED)

    def test_a_document_without_the_build_field_proves_nothing(self):
        fetch = _Origin({f"{API_ORIGIN}{IDENTITY_PATH}": json.dumps({"status": "ok"})})

        failure = validate_deployment_identity(
            SERVED, target=_fronted_target(), fetch=fetch
        )

        assert failure is not None
        self.assertEqual(failure.reason, IDENTITY_PROOF_MALFORMED)

    def test_an_abbreviated_build_is_not_proof(self):
        fetch = _Origin({f"{API_ORIGIN}{IDENTITY_PATH}": _health(SERVED[:12])})

        failure = validate_deployment_identity(
            SERVED, target=_fronted_target(), fetch=fetch
        )

        assert failure is not None
        self.assertEqual(failure.reason, IDENTITY_PROOF_MALFORMED)

    def test_a_json_array_is_not_a_health_document(self):
        fetch = _Origin({f"{API_ORIGIN}{IDENTITY_PATH}": json.dumps([SERVED])})

        failure = validate_deployment_identity(
            SERVED, target=_fronted_target(), fetch=fetch
        )

        assert failure is not None
        self.assertEqual(failure.reason, IDENTITY_PROOF_MALFORMED)


if __name__ == "__main__":
    unittest.main()
