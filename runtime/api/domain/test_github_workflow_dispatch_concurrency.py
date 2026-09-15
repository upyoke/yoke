"""Genuine concurrent races and further non-owner edge cases for GitHub
workflow dispatch intents. Shares fixtures with the sibling
``test_github_workflow_dispatch.py``; see that module's docstring for the
ownership-vs-reuse contract under test.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List

import pytest

from yoke_core.domain import github_actions_rest, github_workflow_dispatch
from yoke_core.domain.github_workflow_dispatch import dispatch_workflow_with_intent
from yoke_core.domain.github_workflow_dispatch_intents import (
    claim_attempt,
    complete_intent,
    latest_intent,
)
from yoke_contracts.github_workflow_dispatch import workflow_dispatch_marker
from runtime.api.domain.test_github_workflow_dispatch_fixtures import (
    REPO,
    REQUEST_ID,
    WORKFLOW,
    build_payload,
    build_request,
    refusing_rest_post,
    seed_intent,
)
from runtime.api.fixtures.file_test_db import init_test_db


def test_concurrent_different_actors_race_first_claim_and_both_rejoin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two different actors both observe no intent and race the real
    ``claim_attempt`` unique-constraint insert; only one wins, and the
    loser's ``_claim_and_post`` recursion rejoins the winner's run through
    the new cross-actor read path — no preseeded intent, no second POST.
    """
    request_id = (
        "workflow-dispatch:racecandidate:raceconsumer:example-consumer-check.yml"
    )
    barrier = threading.Barrier(2)
    real_claim_attempt = claim_attempt

    def synced_claim_attempt(**kwargs: Any) -> bool:
        barrier.wait(timeout=5)
        return real_claim_attempt(**kwargs)

    posted: List[Dict[str, Any]] = []
    post_lock = threading.Lock()
    listing_path = f"/repos/{REPO}/actions/workflows/{WORKFLOW}/runs"

    def fake_rest_post(path: str, *, body: Any, token: str, max_attempts: int) -> Any:
        with post_lock:
            posted.append(body)
        return {
            "workflow_run_id": "77",
            "run_url": "https://api.github.com/.../77",
            "html_url": "https://github.com/.../77",
        }

    def fake_rest_get(path: str, *, query: Any = None, token: str) -> Any:
        if path == listing_path:
            intent = latest_intent(request_id)
            marker = workflow_dispatch_marker(intent.correlation_id) if intent else ""
            return {
                "workflow_runs": [
                    {
                        "id": "77",
                        "display_title": f"release {marker}",
                        "url": "https://api.github.com/.../77",
                        "html_url": "https://github.com/.../77",
                    }
                ]
            }
        return {"id": "77", "status": "completed", "conclusion": "success"}

    results: Dict[str, Any] = {}

    def run(actor_id: str) -> None:
        results[actor_id] = dispatch_workflow_with_intent(
            build_request(actor_id, request_id=request_id), build_payload(), "tok"
        )

    with init_test_db(tmp_path):
        monkeypatch.setattr(
            github_workflow_dispatch, "claim_attempt", synced_claim_attempt
        )
        monkeypatch.setattr(github_actions_rest, "rest_post", fake_rest_post)
        monkeypatch.setattr(github_actions_rest, "rest_get", fake_rest_get)

        threads = [
            threading.Thread(target=run, args=("actor-a",)),
            threading.Thread(target=run, args=("actor-b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    assert len(posted) == 1
    assert set(results) == {"actor-a", "actor-b"}
    for outcome in results.values():
        assert outcome.primary_success is True
        assert outcome.result_payload["run_id"] == "77"


def test_mismatched_authorization_scope_still_collides_regardless_of_actor(
    tmp_path: Path,
) -> None:
    with init_test_db(tmp_path):
        seed_intent(owner_actor="local-operator")

        other_scope_request = build_request("release-ci")
        other_scope_request.options["authorized_project_id"] = 99

        outcome = dispatch_workflow_with_intent(
            other_scope_request, build_payload(), "tok"
        )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "idempotency_key_collision"


def test_cross_actor_pending_with_no_correlated_run_gets_pending_advisory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-owner reading a pending intent whose run is not yet visible on
    GitHub gets the same ambiguous/lost-response advisory an owner would —
    never a collision, and never a POST.
    """
    with init_test_db(tmp_path):
        seed_intent(owner_actor="local-operator", correlation_id="corr-lost")

        def fake_rest_get(path: str, *, query: Any = None, token: str) -> Any:
            return {"workflow_runs": []}

        monkeypatch.setattr(github_actions_rest, "rest_get", fake_rest_get)
        monkeypatch.setattr(github_actions_rest, "rest_post", refusing_rest_post)

        outcome = dispatch_workflow_with_intent(
            build_request("release-ci"), build_payload(), "tok"
        )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "workflow_dispatch_pending"


@pytest.mark.parametrize(
    "run_response",
    [
        pytest.param([], id="malformed-not-a-mapping"),
        pytest.param(
            {"id": "not-999", "status": "completed", "conclusion": "success"},
            id="ambiguous-run-id-mismatch",
        ),
        pytest.param(
            {"id": "999", "status": "weird", "conclusion": ""},
            id="ambiguous-unknown-state",
        ),
    ],
)
def test_cross_actor_ambiguous_run_evidence_refuses_without_posting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_response: Any,
) -> None:
    """A non-owner reading a completed intent whose GitHub evidence is
    malformed or ambiguous is refused, exactly like an owner would be —
    never treated as proof, and never POSTed.
    """
    with init_test_db(tmp_path):
        seed_intent(owner_actor="local-operator")
        complete_intent(
            latest_intent(REQUEST_ID),
            workflow_run_id="999",
            run_url=None,
            html_url=f"https://github.com/{REPO}/actions/runs/999",
        )

        monkeypatch.setattr(
            github_actions_rest, "rest_get", lambda *a, **k: run_response
        )
        monkeypatch.setattr(github_actions_rest, "rest_post", refusing_rest_post)

        outcome = dispatch_workflow_with_intent(
            build_request("release-ci"), build_payload(), "tok"
        )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "rest_transport_error"
