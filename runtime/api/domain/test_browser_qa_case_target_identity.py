"""Browser QA — the target a case browses can answer for itself.

Where nothing was deployed and the project configures no preview proof,
the only thing that can say which commit the evidence is captured against
is the host about to be browsed. These cover both halves of that: the
reading itself is evidence rather than assertion, and the fallback is
last rather than lenient — a preview that answered wrongly, a
configuration that could not be read, and a run-bound deployment failure
each still refuse on their own terms instead of finding a closer host
that happens to say the right thing.
"""

from __future__ import annotations

from yoke_contracts.runtime_identity import (
    SERVED_BUILD_DIRTY_SUFFIX,
    SERVED_BUILD_PATH,
)
from yoke_core.domain import browser_qa_case_target_identity as case_target
from yoke_core.domain import browser_qa_freshness_outcome as outcome
from yoke_core.domain import served_revision_probe as probe


SHA = "a" * 40
OTHER_SHA = "b" * 40
TARGET = "http://127.0.0.1:47311"


def _answering(body: str, *, status: int = 200):
    """A reader that hands back one body, and records the URL it was asked."""
    asked: list[str] = []

    def fetch(url: str) -> probe.ServedRevisionRead:
        asked.append(url)
        return probe.ServedRevisionRead(status=status, body=body)

    return fetch, asked


class TestReadingWhatTheTargetServes:
    """The recorded commit is the target's answer, never the caller's ask."""

    def test_the_commit_returned_is_the_one_the_target_served(self) -> None:
        fetch, asked = _answering(SHA)

        failure, served = case_target.verify_case_target_identity(
            TARGET, SHA, fetch=fetch
        )

        assert failure is None
        assert served == SHA
        assert asked == [f"{TARGET}{SERVED_BUILD_PATH}"]

    def test_a_target_serving_another_commit_is_refused(self) -> None:
        fetch, _ = _answering(OTHER_SHA)

        failure, served = case_target.verify_case_target_identity(
            TARGET, SHA, fetch=fetch
        )

        assert failure is not None
        assert failure.reason == outcome.SHA_MISMATCH
        assert OTHER_SHA in failure.message
        assert served == "", "a refused reading is not a commit anything served"

    def test_a_dirty_serving_tree_is_refused_by_name(self) -> None:
        """The failure this prevents: certifying screenshots of uncommitted
        work as evidence about the commit that does not contain it."""
        fetch, _ = _answering(f"{SHA}{SERVED_BUILD_DIRTY_SUFFIX}")

        failure, served = case_target.verify_case_target_identity(
            TARGET, SHA, fetch=fetch
        )

        assert failure is not None
        assert failure.reason == outcome.IDENTITY_PROOF_MALFORMED
        assert "uncommitted changes" in failure.message
        assert served == ""

    def test_an_unreachable_target_is_unverified_rather_than_stale(self) -> None:
        def fetch(url: str) -> probe.ServedRevisionRead:
            return probe.ServedRevisionRead(error="connection refused")

        failure, served = case_target.verify_case_target_identity(
            TARGET, SHA, fetch=fetch
        )

        assert failure is not None
        assert failure.reason == outcome.IDENTITY_PROOF_UNAVAILABLE
        assert "unverified rather than stale" in failure.message
        assert served == ""

    def test_a_target_that_names_no_commit_is_refused(self) -> None:
        fetch, _ = _answering("")

        failure, served = case_target.verify_case_target_identity(
            TARGET, SHA, fetch=fetch
        )

        assert failure is not None
        assert failure.reason == outcome.IDENTITY_PROOF_MALFORMED
        assert served == ""

    def test_an_abbreviated_commit_is_not_proof(self) -> None:
        fetch, _ = _answering(SHA[:12])

        failure, _ = case_target.verify_case_target_identity(
            TARGET, SHA, fetch=fetch
        )

        assert failure is not None
        assert failure.reason == outcome.IDENTITY_PROOF_MALFORMED

    def test_a_case_naming_no_host_is_refused(self) -> None:
        failure, served = case_target.verify_case_target_identity("", SHA)

        assert failure is not None
        assert failure.reason == outcome.IDENTITY_PROOF_UNAVAILABLE
        assert served == ""


class TestCredentialsStayOutOfEvidence:
    """A case URL may carry a session token; a refusal message outlives it.

    The failure this prevents: a token pasted into a run's recorded result
    or a reviewer-visible refusal, where it is readable long after the run.
    """

    CREDENTIALED = "http://operator:hunter2@127.0.0.1:47311/?token=s3cret"

    def test_the_identity_request_carries_no_credential_in_its_url(self) -> None:
        fetch, asked = _answering(SHA)

        case_target.verify_case_target_identity(
            self.CREDENTIALED, SHA, fetch=fetch
        )

        assert asked == [f"{TARGET}{SERVED_BUILD_PATH}"]
        assert "s3cret" not in asked[0]
        assert "hunter2" not in asked[0]

    def test_a_refusal_message_carries_no_credential(self) -> None:
        fetch, _ = _answering(OTHER_SHA)

        failure, _ = case_target.verify_case_target_identity(
            self.CREDENTIALED, SHA, fetch=fetch
        )

        assert failure is not None
        assert "s3cret" not in failure.message
        assert "hunter2" not in failure.message

    def test_the_origin_bound_to_execution_carries_no_credential(self) -> None:
        assert case_target.credential_free_origin(self.CREDENTIALED) == TARGET

    def test_the_session_reader_refuses_to_follow_another_host(self) -> None:
        """Credentials are presented to the case origin and nowhere else."""
        redirect = probe.OriginBoundRedirect(TARGET)

        assert redirect.redirect_request(
            None, None, 302, "", {}, "https://elsewhere.example.test/x"
        ) is None
