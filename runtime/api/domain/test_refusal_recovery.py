"""Refusal reason and recovery are separately checkable."""

from __future__ import annotations

import pytest

from yoke_core.domain.deployment_qa_stage_acceptance import (
    unsettled_acceptance_blocker,
)
from yoke_core.domain.qa_plan_target_reuse_refusal import different_target_refusal
from yoke_core.domain.refusal_recovery import compose_refusal


def test_compose_refusal_requires_recovery_or_escalation() -> None:
    with pytest.raises(ValueError, match="escalate"):
        compose_refusal("the gate failed")
    with pytest.raises(ValueError, match="not both"):
        compose_refusal(
            "the gate failed",
            recovery="retry",
            escalate_to="the operator",
        )


def test_compose_refusal_reports_evaluated_state_and_recovery() -> None:
    text = compose_refusal(
        "the gate failed",
        evaluated="cases passed; digest matched",
        recovery="re-drive the run",
        unavailable=("retry locally",),
    )
    assert "the gate failed" in text
    assert "Evaluated: cases passed; digest matched" in text
    assert "Not available: retry locally" in text
    assert "Recovery: re-drive the run" in text


def test_unsettled_acceptance_names_matched_execution_and_re_drive() -> None:
    text = unsettled_acceptance_blocker(
        execution_id="exec-1", digest="abc123"
    )
    assert "never settled against this deployment target" in text
    assert "completed scoped execution exec-1 matches digest abc123" in text
    assert "no case failed" in text
    assert "re-drive the deployment run" in text
    assert "no member or worker action" in text


def _same_identity(*, app_url: str) -> dict[str, object]:
    return {
        "schema": 1,
        "tenant": {"id": 1, "slug": "acme"},
        "project": {"id": 1, "slug": "app"},
        "site": {"name": "primary"},
        "environment": {
            "id": 7,
            "name": "development",
            "kind": "persistent_environment",
        },
        "endpoints": {"app_url": app_url},
    }


def test_different_target_omits_unreachable_remedies_when_passed() -> None:
    text = different_target_refusal(
        subject="item 101 transition 'release'",
        requirement_id=101,
        stored_digest="old",
        expected_digest="new",
        latest_verdict="pass",
        has_runs=True,
        item_bound=True,
    )
    assert "bound to a different execution target" in text
    assert "stored digest old vs current new" in text
    assert "already recorded a passing verdict" in text
    assert "cannot replace requirement 101" in text
    assert "workers must not create a deployment run" in text
    assert "No reachable recovery from this call" in text
    assert "escalate to the operator" in text
    assert "Recovery:" not in text
    assert "supersede" not in text
    assert "retire or supersede" not in text


def test_different_target_names_rebind_when_declaration_moved() -> None:
    text = different_target_refusal(
        subject="item 101 transition implemented",
        requirement_id=101,
        stored_digest="old",
        expected_digest="new",
        latest_verdict="pass",
        has_runs=True,
        item_bound=True,
        stored_target=_same_identity(app_url="https://app.example.test"),
        current_target=_same_identity(app_url="http://app.example.test"),
    )
    assert "rebind-target" in text
    assert "Recovery:" in text
    assert "start a fresh" not in text
    assert "No reachable recovery from this call" not in text


def test_different_target_does_not_name_rebind_when_host_authority_moved() -> None:
    text = different_target_refusal(
        subject="item 101 transition implemented",
        requirement_id=101,
        stored_digest="old",
        expected_digest="new",
        latest_verdict="pass",
        has_runs=True,
        item_bound=True,
        stored_target=_same_identity(app_url="https://app.example.test"),
        current_target=_same_identity(app_url="https://other.example.test"),
    )
    assert "rebind-target" not in text
    assert "start a fresh" in text
    assert "supersede" not in text


def _stale_site(app_url: str, *, site: str) -> dict[str, object]:
    target = _same_identity(app_url=app_url)
    target["site"] = {"name": site}
    environment = dict(target["environment"])  # type: ignore[arg-type]
    environment.pop("id", None)
    target["environment"] = environment
    return target


def test_different_target_names_rebind_when_endpoints_match_stale_labels() -> None:
    text = different_target_refusal(
        subject="item 101 transition implemented",
        requirement_id=101,
        stored_digest="old",
        expected_digest="new",
        latest_verdict="pass",
        has_runs=True,
        item_bound=True,
        stored_target=_stale_site("https://app.upyoke.com", site="Yoke API"),
        current_target=_stale_site("https://app.upyoke.com", site="yoke"),
    )
    assert "rebind-target" in text
    assert "Recovery:" in text
    assert "identity labels are stale" in text
    assert "No reachable recovery from this call" not in text
    assert "supersede" not in text


def test_different_target_omits_supersede_when_stale_labels_and_host_moved() -> None:
    text = different_target_refusal(
        subject="item 101 transition implemented",
        requirement_id=101,
        stored_digest="old",
        expected_digest="new",
        latest_verdict="pass",
        has_runs=True,
        item_bound=True,
        stored_target=_stale_site("https://app.upyoke.com", site="Yoke API"),
        current_target=_stale_site("https://other.example.test", site="yoke"),
    )
    assert "rebind-target" not in text
    assert "supersede" not in text
    assert "live item requirement" in text
