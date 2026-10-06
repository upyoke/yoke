"""A pre-merge candidate is proved at the target the run was given.

A plan bound to production used to be asked first, so a candidate SHA was
refused against production and the review server was never the proof. These
pin the opposite: the given target is asked at ``/served-build``, production
is not, and a different commit still refuses by name.
"""

from __future__ import annotations

from yoke_contracts.runtime_identity import SERVED_BUILD_PATH
from yoke_core.domain.browser_qa_freshness import _establish_deployment_freshness
from yoke_core.domain.browser_qa_freshness_outcome import SHA_MISMATCH
from yoke_core.domain.served_revision_probe import ServedRevisionRead

PRODUCTION = "https://app.upyoke.com"
CANDIDATE = "http://127.0.0.1:58817/?token=session"
EXPECTED = "a" * 40
OTHER = "b" * 40


def _production_target() -> dict:
    return {
        "environment": "prod",
        "origin": PRODUCTION,
        "identity_path": SERVED_BUILD_PATH,
        "identity_error": "",
        "unresolved": "",
    }


def _fetch(body: str, asked: list[str]):
    def fetch(url: str) -> ServedRevisionRead:
        asked.append(url)
        return ServedRevisionRead(status=200, body=body)

    return fetch


def test_pre_merge_candidate_is_proved_at_the_given_target() -> None:
    asked: list[str] = []

    failure, origin, served = _establish_deployment_freshness(
        "yoke",
        "lane",
        EXPECTED,
        context={"deployment_target": _production_target()},
        base_url=CANDIDATE,
        fetch_identity=_fetch(EXPECTED, asked),
    )

    assert failure is None
    assert origin == "http://127.0.0.1:58817"
    assert served == EXPECTED
    assert asked == [f"http://127.0.0.1:58817{SERVED_BUILD_PATH}"]
    assert all(PRODUCTION not in url for url in asked)


def test_a_candidate_serving_another_commit_refuses_by_name() -> None:
    failure, origin, served = _establish_deployment_freshness(
        "yoke",
        "lane",
        EXPECTED,
        context={"deployment_target": _production_target()},
        base_url=CANDIDATE,
        fetch_identity=_fetch(OTHER, []),
    )

    assert failure is not None
    assert failure.reason == SHA_MISMATCH
    assert origin == ""
    assert served == ""
    assert OTHER in failure.message
    assert EXPECTED in failure.message


def test_a_deployment_run_still_asks_its_bound_environment() -> None:
    asked: list[str] = []

    failure, origin, served = _establish_deployment_freshness(
        "yoke",
        "main",
        EXPECTED,
        context={
            "deployment_run_id": "run-1",
            "deployment_target": _production_target(),
        },
        base_url=CANDIDATE,
        fetch_identity=_fetch(EXPECTED, asked),
    )

    assert failure is None
    assert origin == PRODUCTION
    assert served == EXPECTED
    assert asked == [f"{PRODUCTION}{SERVED_BUILD_PATH}"]
