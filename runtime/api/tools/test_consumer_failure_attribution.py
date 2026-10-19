"""Consumer failures expose the producer release interval and its item provenance."""

from __future__ import annotations

import subprocess

import pytest

from runtime.api.tools.consumer_failure_attribution import producer_failure_context
from runtime.api.tools import require_platform_consumer_compatibility as gate

FIRST_ITEM = f"SOURCE-{42}"
SECOND_ITEM = f"SOURCE-{43}"


@pytest.fixture
def history(tmp_path):
    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(tmp_path), *args], text=True
        ).strip()

    git("init", "--initial-branch=main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("commit", "--allow-empty", "-m", "Initial source")
    baseline = git("rev-parse", "HEAD")
    git("tag", "-a", "v1.0.0", "-m", "Prior release")
    git("commit", "--allow-empty", "-m", f"Merge PR from {FIRST_ITEM}")
    git("commit", "--allow-empty", "-m", f"Follow-up {SECOND_ITEM}")
    candidate = git("rev-parse", "HEAD")
    return tmp_path, git, baseline, candidate


def test_failure_names_prior_release_range_and_producer_items(history):
    root, _, baseline, candidate = history
    text = producer_failure_context(candidate, checkout=root)
    assert f"{baseline}..{candidate}" in text
    assert FIRST_ITEM in text and SECOND_ITEM in text
    assert "v1.0.0" in text
    assert "not a proven single culprit" in text


def test_candidate_tag_does_not_hide_its_introduced_changes(history):
    root, git, baseline, candidate = history
    git("tag", "-a", "v1.0.1", "-m", "Candidate release")
    assert f"{baseline}..{candidate}" in producer_failure_context(
        candidate, checkout=root
    )


def test_bootstrap_without_prior_tag_names_complete_ancestry(history):
    root, git, baseline, candidate = history
    git("tag", "-d", "v1.0.0")
    text = producer_failure_context(candidate, checkout=root)
    assert f"repository roots {baseline} through {candidate}" in text
    assert "no prior annotated release baseline" in text


def test_unreadable_history_names_recovery_and_never_invents_an_item(tmp_path):
    candidate = "a" * 40
    text = producer_failure_context(candidate, checkout=tmp_path)
    assert "producer_attribution_unavailable" in text
    assert candidate in text and "fetch-depth: 0" in text
    assert "Producer item references:" not in text


def test_release_failure_keeps_consumer_run_and_names_producer(history, monkeypatch):
    root, _, baseline, candidate = history
    monkeypatch.chdir(root)
    consumer = "b" * 40
    code, text, proven = gate.classify(
        {
            "state": "failed",
            "conclusion": "failure",
            "head_sha": consumer,
            "html_url": "https://example.invalid/run/1",
        },
        candidate_sha=candidate,
        consumer_sha=consumer,
        run_id="1",
    )
    assert code == gate.UNPROVEN and proven == ""
    assert "https://example.invalid/run/1" in text and consumer in text
    assert f"{baseline}..{candidate}" in text and FIRST_ITEM in text
