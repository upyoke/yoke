"""Contracts for the public contributor-license workflow."""

from pathlib import Path


_WORKFLOW = Path(__file__).resolve().parents[3] / ".github/workflows/cla.yml"


def test_irrelevant_issue_comments_skip_the_cla_job() -> None:
    text = _WORKFLOW.read_text()
    job = text.split("  signature-check:\n", 1)[1]
    guard, steps = job.split("    steps:\n", 1)

    assert "github.event_name == 'pull_request_target'" in guard
    assert "github.event.issue.pull_request" in guard
    assert "github.event.comment.body == 'recheck'" in guard
    assert "I have read the CLA Document and I hereby sign the CLA" in guard
    assert "\n        if:" not in steps


def test_cla_action_stays_commit_pinned() -> None:
    text = _WORKFLOW.read_text()

    assert (
        "uses: contributor-assistant/github-action@"
        "ca4a40a7d1004f18d9960b404b97e5f30a505a08"
    ) in text
