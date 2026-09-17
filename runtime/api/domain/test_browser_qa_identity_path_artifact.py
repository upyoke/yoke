"""Which artifact answers when one host fronts several of them.

A configured identity path selects the artifact as well as the route: a
deployment reached under a prefix is asked there, and the shell at the front
door is a different artifact whose liveness reply proves nothing about the
code under test. Nothing infers which is which — these cover that the
configured path is carried intact, and that whichever base answers, a reply
stating no full commit SHA is refused.
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

ORIGIN = "https://app.example.test"
#: The deployment under test is reached beneath a prefix of this host, so the
#: configured path carries that prefix rather than naming the bare route.
ARTIFACT_PATH = "/api/orgs/example/v1/health"
#: The same route at the front door belongs to the shell, not the deployment.
FRONT_DOOR_PATH = "/v1/health"

FRONT_DOOR_REPLY = json.dumps({"ok": True, "service": "app-shell"})


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


class _Host:
    """Answers each URL it knows and records every URL it was asked for."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def __call__(self, url: str) -> probe.ServedRevisionRead:
        self.asked.append(url)
        if url not in self.answers:
            return probe.ServedRevisionRead(status=404, error="HTTP 404")
        return probe.ServedRevisionRead(status=200, body=self.answers[url])


def _target(path: str, origin: str = ORIGIN) -> DeploymentUnderTest:
    return DeploymentUnderTest(environment="prod", origin=origin, identity_path=path)


def _both_artifacts() -> _Host:
    return _Host(
        {
            f"{ORIGIN}{ARTIFACT_PATH}": _health(SERVED),
            f"{ORIGIN}{FRONT_DOOR_PATH}": FRONT_DOOR_REPLY,
        }
    )


class TestConfiguredPathSelectsTheArtifact(unittest.TestCase):
    def test_the_configured_prefix_reaches_the_deployment_under_test(self):
        """Every segment of the configured path survives to the request."""
        fetch = _both_artifacts()

        failure = validate_deployment_identity(
            SERVED, target=_target(ARTIFACT_PATH), fetch=fetch
        )

        self.assertIsNone(failure)
        self.assertEqual(fetch.asked, [f"{ORIGIN}{ARTIFACT_PATH}"])

    def test_the_front_door_reply_proves_nothing_about_the_deployment(self):
        """A neighbouring artifact's liveness is a refusal, not a pass."""
        fetch = _both_artifacts()

        failure = validate_deployment_identity(
            SERVED, target=_target(FRONT_DOOR_PATH), fetch=fetch
        )

        assert failure is not None
        self.assertEqual(failure.reason, IDENTITY_PROOF_MALFORMED)
        self.assertIn("app-shell", failure.message)

    def test_a_host_serving_one_artifact_reads_as_it_always_did(self):
        """A project whose host is its deployment needs no prefix at all."""
        origin = "https://single.example.test"
        fetch = _Host({f"{origin}/candidate-revision": SERVED})

        failure = validate_deployment_identity(
            SERVED, target=_target("/candidate-revision", origin), fetch=fetch
        )

        self.assertIsNone(failure)
        self.assertEqual(fetch.asked, [f"{origin}/candidate-revision"])

    def test_an_origin_carrying_its_own_path_is_still_reduced(self):
        """The rule against a base smuggling a path is untouched."""
        fetch = _Host({f"{ORIGIN}/candidate-revision": SERVED})

        failure = validate_deployment_identity(
            SERVED,
            target=_target("/candidate-revision", f"{ORIGIN}/somewhere/else"),
            fetch=fetch,
        )

        self.assertIsNone(failure)
        self.assertEqual(fetch.asked, [f"{ORIGIN}/candidate-revision"])


class TestHealthDocumentRevision(unittest.TestCase):
    def test_a_bare_revision_body_is_still_the_whole_answer(self):
        fetch = _Host({f"{ORIGIN}{ARTIFACT_PATH}": SERVED})

        failure = validate_deployment_identity(
            SERVED, target=_target(ARTIFACT_PATH), fetch=fetch
        )

        self.assertIsNone(failure)

    def test_a_health_document_naming_another_build_is_a_mismatch(self):
        fetch = _Host({f"{ORIGIN}{ARTIFACT_PATH}": _health(OTHER)})

        failure = validate_deployment_identity(
            SERVED, target=_target(ARTIFACT_PATH), fetch=fetch
        )

        assert failure is not None
        self.assertEqual(failure.reason, SHA_MISMATCH)
        self.assertIn(OTHER, failure.message)

    def test_an_unparseable_document_proves_nothing(self):
        fetch = _Host({f"{ORIGIN}{ARTIFACT_PATH}": _health(SERVED)[:40]})

        failure = validate_deployment_identity(
            SERVED, target=_target(ARTIFACT_PATH), fetch=fetch
        )

        assert failure is not None
        self.assertEqual(failure.reason, IDENTITY_PROOF_MALFORMED)

    def test_a_document_without_the_build_field_proves_nothing(self):
        fetch = _Host({f"{ORIGIN}{ARTIFACT_PATH}": json.dumps({"status": "ok"})})

        failure = validate_deployment_identity(
            SERVED, target=_target(ARTIFACT_PATH), fetch=fetch
        )

        assert failure is not None
        self.assertEqual(failure.reason, IDENTITY_PROOF_MALFORMED)

    def test_an_abbreviated_build_is_not_proof(self):
        fetch = _Host({f"{ORIGIN}{ARTIFACT_PATH}": _health(SERVED[:12])})

        failure = validate_deployment_identity(
            SERVED, target=_target(ARTIFACT_PATH), fetch=fetch
        )

        assert failure is not None
        self.assertEqual(failure.reason, IDENTITY_PROOF_MALFORMED)

    def test_a_json_array_is_not_a_health_document(self):
        fetch = _Host({f"{ORIGIN}{ARTIFACT_PATH}": json.dumps([SERVED])})

        failure = validate_deployment_identity(
            SERVED, target=_target(ARTIFACT_PATH), fetch=fetch
        )

        assert failure is not None
        self.assertEqual(failure.reason, IDENTITY_PROOF_MALFORMED)


if __name__ == "__main__":
    unittest.main()
