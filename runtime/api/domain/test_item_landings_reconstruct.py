"""Git merge subjects become landing facts, or they are skipped."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from yoke_core.domain.item_landings_close_out import landing_route
from yoke_core.domain.item_landings_reconstruct import (
    fact_from_log_fields,
    facts_from_json,
    facts_to_json,
    parse_merge_subject,
    walk_merge_history,
)
from yoke_core.domain.item_landings_schema import ROUTE_FAST_FORWARD, ROUTE_MERGE_QUEUE


def _git(repo: str, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
    }
    subprocess.run(
        ["git", "-C", repo, *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _repo_with_yok_merge() -> str:
    repo = tempfile.mkdtemp(prefix="yoke-landings-git-")
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.email", "t@x")
    _git(repo, "config", "user.name", "t")
    Path(repo, "a.txt").write_text("base\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "YOK-99")
    Path(repo, "a.txt").write_text("lane\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "lane")
    _git(repo, "checkout", "main")
    _git(
        repo,
        "merge",
        "--no-ff",
        "YOK-99",
        "-m",
        "Merge pull request #7 from upyoke/YOK-99",
    )
    return repo


def test_a_github_pr_subject_names_the_branch_sequence_and_number() -> None:
    parsed = parse_merge_subject(
        "Merge pull request #1379 from upyoke/YOK-3307"
    )
    assert parsed == (3307, "1379")


def test_a_subject_that_mentions_yok_but_did_not_merge_that_branch_is_skipped() -> None:
    """Titles mention work items; only the branch name is the landing identity."""
    assert parse_merge_subject(
        "Merge origin/main to keep landed YOK-3307 dismissal."
    ) is None
    assert parse_merge_subject(
        "Merge pull request #180 from upyoke/merge-queue-marker-cleanup"
    ) is None


def test_a_suffixed_yok_branch_still_resolves_the_sequence() -> None:
    parsed = parse_merge_subject(
        "Merge pull request #12 from upyoke/YOK-4-follow-up"
    )
    assert parsed == (4, "12")


def test_a_two_parent_merge_is_classified_by_landing_route() -> None:
    fact = fact_from_log_fields(
        "b" * 40,
        f"{'a' * 40} {'c' * 40}",
        "1789942504",
        "Merge pull request #1379 from upyoke/YOK-3307",
    )
    assert fact is not None
    assert fact.project_sequence == 3307
    assert fact.pr_number == "1379"
    assert fact.candidate_sha == "c" * 40
    assert landing_route(
        merge_sha=fact.merge_sha,
        candidate_sha=fact.candidate_sha,
        pr_number=fact.pr_number,
    ) == ROUTE_MERGE_QUEUE


def test_a_merge_without_a_second_parent_is_a_fast_forward_route() -> None:
    fact = fact_from_log_fields(
        "b" * 40,
        "a" * 40,
        "1789942504",
        "Merge pull request #2 from upyoke/YOK-8",
    )
    assert fact is not None
    assert fact.candidate_sha == "b" * 40
    assert landing_route(
        merge_sha=fact.merge_sha,
        candidate_sha=fact.candidate_sha,
        pr_number=fact.pr_number,
    ) == ROUTE_FAST_FORWARD


def test_walk_reads_a_real_merge_commit() -> None:
    repo = _repo_with_yok_merge()
    walked = walk_merge_history(repo, revision="main")
    assert walked.skipped_unresolved_branch == 0
    assert len(walked.facts) == 1
    assert walked.facts[0].project_sequence == 99
    assert walked.facts[0].pr_number == "7"
    assert walked.facts[0].target_branch == "main"


def test_json_round_trip_keeps_the_git_fields() -> None:
    repo = _repo_with_yok_merge()
    walked = walk_merge_history(repo, revision="main")
    restored = facts_from_json(facts_to_json(walked.facts))
    assert restored == walked.facts
