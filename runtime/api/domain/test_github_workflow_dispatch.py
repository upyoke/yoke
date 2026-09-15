"""Cross-actor proof reuse for durable GitHub workflow dispatch intents.

Two independently authorized callers sharing one deterministic
``request_id`` for the identical logical dispatch (same repo, workflow,
ref, and inputs) may authenticate as different actors within the same
authorized scope. Reading an already-running or already-completed proof
must not require actor equality; only *owning* the dispatch mutation
(posting a fresh attempt, retriggering after failure) does. See
``packages/yoke-core/src/yoke_core/domain/github_workflow_dispatch.py``
for the split between ``_same_logical_request`` (ownership) and
``_proof_reusable`` (read authorization). Genuinely concurrent races and
further non-owner edge cases live in the sibling
``test_github_workflow_dispatch_concurrency.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from yoke_contracts.github_workflow_dispatch import workflow_dispatch_marker
from yoke_core.domain import github_actions_rest
from yoke_core.domain.github_workflow_dispatch import dispatch_workflow_with_intent
from yoke_core.domain.github_workflow_dispatch_intents import (
    complete_intent,
    latest_intent,
    reject_intent,
)
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


def test_cross_actor_reuses_completed_successful_intent_without_posting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with init_test_db(tmp_path):
        seed_intent(owner_actor="local-operator")
        complete_intent(
            latest_intent(REQUEST_ID),
            workflow_run_id="999",
            run_url=f"https://api.github.com/repos/{REPO}/actions/runs/999",
            html_url=f"https://github.com/{REPO}/actions/runs/999",
        )

        def fake_rest_get(path: str, *, query: Any = None, token: str) -> Any:
            assert path == f"/repos/{REPO}/actions/runs/999"
            return {"id": "999", "status": "completed", "conclusion": "success"}

        monkeypatch.setattr(github_actions_rest, "rest_get", fake_rest_get)
        monkeypatch.setattr(github_actions_rest, "rest_post", refusing_rest_post)

        outcome = dispatch_workflow_with_intent(
            build_request("release-ci"), build_payload(), "tok"
        )

    assert outcome.primary_success is True
    assert outcome.result_payload["dispatched"] is False
    assert outcome.result_payload["run_id"] == "999"


def test_cross_actor_reads_failed_run_without_retriggering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with init_test_db(tmp_path):
        seed_intent(owner_actor="local-operator")
        complete_intent(
            latest_intent(REQUEST_ID),
            workflow_run_id="999",
            run_url=None,
            html_url=f"https://github.com/{REPO}/actions/runs/999",
        )

        def fake_rest_get(path: str, *, query: Any = None, token: str) -> Any:
            return {"id": "999", "status": "completed", "conclusion": "failure"}

        monkeypatch.setattr(github_actions_rest, "rest_get", fake_rest_get)
        monkeypatch.setattr(github_actions_rest, "rest_post", refusing_rest_post)

        outcome = dispatch_workflow_with_intent(
            build_request("release-ci"), build_payload(), "tok"
        )

    # Not retriggered: the reading actor is told what the proof shows
    # (a failed run) so its own classification reports it, rather than
    # a mutation it does not own being retried under its identity.
    assert outcome.primary_success is True
    assert outcome.result_payload["dispatched"] is False
    assert outcome.result_payload["run_id"] == "999"


def test_owner_still_retriggers_after_failed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with init_test_db(tmp_path):
        seed_intent(owner_actor="local-operator")
        complete_intent(
            latest_intent(REQUEST_ID),
            workflow_run_id="999",
            run_url=None,
            html_url=f"https://github.com/{REPO}/actions/runs/999",
        )

        def fake_rest_get(path: str, *, query: Any = None, token: str) -> Any:
            return {"id": "999", "status": "completed", "conclusion": "failure"}

        posted: List[Dict[str, Any]] = []

        def fake_rest_post(
            path: str, *, body: Any, token: str, max_attempts: int
        ) -> Any:
            posted.append(body)
            return {
                "workflow_run_id": "1000",
                "run_url": "https://api.github.com/.../1000",
                "html_url": "https://github.com/.../1000",
            }

        monkeypatch.setattr(github_actions_rest, "rest_get", fake_rest_get)
        monkeypatch.setattr(github_actions_rest, "rest_post", fake_rest_post)

        outcome = dispatch_workflow_with_intent(
            build_request("local-operator"), build_payload(), "tok"
        )

    assert outcome.primary_success is True
    assert outcome.result_payload["dispatched"] is True
    assert outcome.result_payload["run_id"] == "1000"
    assert len(posted) == 1


def test_cross_actor_reads_pending_intent_by_correlation_without_posting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with init_test_db(tmp_path):
        seed_intent(owner_actor="local-operator", correlation_id="corr-pending")
        marker = workflow_dispatch_marker("corr-pending")
        listing_path = f"/repos/{REPO}/actions/workflows/{WORKFLOW}/runs"

        def fake_rest_get(path: str, *, query: Any = None, token: str) -> Any:
            if path == listing_path:
                return {
                    "workflow_runs": [
                        {
                            "id": "999",
                            "display_title": f"release {marker}",
                            "url": "https://api.github.com/.../999",
                            "html_url": "https://github.com/.../999",
                        }
                    ]
                }
            assert path == f"/repos/{REPO}/actions/runs/999"
            return {"id": "999", "status": "completed", "conclusion": "success"}

        monkeypatch.setattr(github_actions_rest, "rest_get", fake_rest_get)
        monkeypatch.setattr(github_actions_rest, "rest_post", refusing_rest_post)

        outcome = dispatch_workflow_with_intent(
            build_request("release-ci"), build_payload(), "tok"
        )
        assert latest_intent(REQUEST_ID).state == "completed"

    assert outcome.primary_success is True
    assert outcome.result_payload["dispatched"] is False
    assert outcome.result_payload["run_id"] == "999"


def test_rejected_intent_still_refuses_a_non_owning_actor(tmp_path: Path) -> None:
    with init_test_db(tmp_path):
        seed_intent(owner_actor="local-operator")
        reject_intent(latest_intent(REQUEST_ID))

        outcome = dispatch_workflow_with_intent(
            build_request("release-ci"), build_payload(), "tok"
        )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "idempotency_key_collision"


def test_fresh_pair_first_dispatch_then_same_actor_rejoins_without_reposting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A brand-new pair's request_id was never dispatched, so the first call
    from any actor claims it cleanly — unchanged owner-first semantics, the
    same path an unmodified server already runs today. A later call from
    that SAME actor (e.g. a second pipeline stage sharing one CI token)
    then rejoins the completed intent without a repeat POST.
    """
    fresh_request_id = (
        "workflow-dispatch:freshcandidate:freshconsumer:example-consumer-check.yml"
    )
    posted: List[Dict[str, Any]] = []

    def fake_rest_post(path: str, *, body: Any, token: str, max_attempts: int) -> Any:
        posted.append(body)
        return {
            "workflow_run_id": "42",
            "run_url": "https://api.github.com/.../42",
            "html_url": "https://github.com/.../42",
        }

    def fake_rest_get(path: str, *, query: Any = None, token: str) -> Any:
        return {"id": "42", "status": "completed", "conclusion": "success"}

    with init_test_db(tmp_path):
        monkeypatch.setattr(github_actions_rest, "rest_post", fake_rest_post)
        monkeypatch.setattr(github_actions_rest, "rest_get", fake_rest_get)

        first_outcome = dispatch_workflow_with_intent(
            build_request("release-ci", request_id=fresh_request_id),
            build_payload(),
            "tok",
        )
        assert first_outcome.result_payload["dispatched"] is True
        assert len(posted) == 1

        monkeypatch.setattr(github_actions_rest, "rest_post", refusing_rest_post)
        second_outcome = dispatch_workflow_with_intent(
            build_request("release-ci", request_id=fresh_request_id),
            build_payload(),
            "tok",
        )

    assert second_outcome.primary_success is True
    assert second_outcome.result_payload["dispatched"] is False
    assert second_outcome.result_payload["run_id"] == "42"
    assert len(posted) == 1


def test_mismatched_payload_still_collides_regardless_of_actor(tmp_path: Path) -> None:
    with init_test_db(tmp_path):
        seed_intent(owner_actor="local-operator")
        complete_intent(
            latest_intent(REQUEST_ID),
            workflow_run_id="999",
            run_url=None,
            html_url="https://github.com/.../999",
        )

        different_payload_request = build_request("release-ci")
        different_payload_request.payload["inputs"] = {"product_ref": "othersha"}

        outcome = dispatch_workflow_with_intent(
            different_payload_request, build_payload(), "tok"
        )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "idempotency_key_collision"
