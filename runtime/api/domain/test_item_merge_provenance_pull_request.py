"""Operator repair of which pull request carried an item's landing.

The marker an item records decides which pull request every later landing
question is asked of. When it names one that never merged — the shape a
sibling pull request carrying the same commits produces — close-out keeps
asking that open pull request about a merge it never performed, and no
retry can change the answer. These tests pin the repair and the verification
that keeps it from becoming an assertion.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain import item_merge_provenance_pull_request as repair
from yoke_core.domain.item_merge_provenance_operator import (
    MergedAtCorrectionError,
    MergedAtCorrectionHookContextError,
)
from yoke_core.domain.merge_queue_landing_marker import (
    point_item_at_pull_request,
    read_landing_marker,
)
from yoke_core.domain.merge_queue_landing_record_schema import (
    ensure_merge_queue_landing_record_schema,
)

ITEM_ID = 4301
REASON = "PR 1259 never merged; 1276 carried these commits"
MERGE_SHA = "9" * 40


class _Auth:
    repo = "owner/repo"
    token = "token"


def _seed(conn, *, pr_number: str = "1259") -> None:
    # The repoint drops the predecessor's observation row, so the table it
    # lives in has to exist as it does in a converged universe.
    ensure_merge_queue_landing_record_schema(conn)
    insert_item(
        conn,
        id=ITEM_ID,
        title="Item whose carrier was a sibling pull request",
        workflow_id="dash",
        status="release",
    )
    point_item_at_pull_request(conn, ITEM_ID, pr_number, enqueued_at="2026-09-18T00:00:00Z")


def _github(monkeypatch, body: dict | Exception) -> list[str]:
    paths: list[str] = []

    def _request(request, *, token):
        del token
        paths.append(request.path)
        if isinstance(body, Exception):
            raise body
        return type("Response", (), {"status": 200, "headers": {}, "body": body})()

    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda *_a, **_k: _Auth(),
    )
    monkeypatch.setattr(
        "yoke_core.domain.gh_rest_transport.request_with_retry", _request
    )
    return paths


def test_repointing_at_the_merged_carrier_replaces_the_marker(
    test_db, monkeypatch
):
    _seed(test_db)
    paths = _github(monkeypatch, {"merged": True, "merge_commit_sha": MERGE_SHA})

    result = repair.operator_correct_landing_pull_request(
        test_db, ITEM_ID, "1276", REASON
    )

    assert result["corrected"] is True
    assert result["previous_pr_number"] == "1259"
    assert result["pr_number"] == "1276"
    assert result["merge_commit_sha"] == MERGE_SHA
    assert read_landing_marker(test_db, ITEM_ID)["pr_number"] == "1276"
    assert paths == ["/repos/owner/repo/pulls/1276"]


def test_the_predecessors_queue_admission_does_not_follow_the_repoint(
    test_db, monkeypatch
):
    """Stamps belong to the pull request that earned them."""
    _seed(test_db)
    _github(monkeypatch, {"merged": True, "merge_commit_sha": MERGE_SHA})

    repair.operator_correct_landing_pull_request(test_db, ITEM_ID, "1276", REASON)

    assert read_landing_marker(test_db, ITEM_ID)["enqueued_at"] == ""


def test_an_unmerged_pull_request_is_refused_by_name(test_db, monkeypatch):
    _seed(test_db)
    _github(monkeypatch, {"merged": False, "merge_commit_sha": MERGE_SHA})

    with pytest.raises(MergedAtCorrectionError) as refusal:
        repair.operator_correct_landing_pull_request(
            test_db, ITEM_ID, "1277", REASON
        )

    # GitHub reports a merge_commit_sha for an open pull request too -- its
    # own test merge -- so the merged flag is what the refusal reads.
    assert "has not merged" in str(refusal.value)
    assert read_landing_marker(test_db, ITEM_ID)["pr_number"] == "1259"


def test_a_reason_is_required(test_db, monkeypatch):
    _seed(test_db)
    _github(monkeypatch, {"merged": True, "merge_commit_sha": MERGE_SHA})

    with pytest.raises(MergedAtCorrectionError):
        repair.operator_correct_landing_pull_request(test_db, ITEM_ID, "1276", "  ")


def test_a_hook_context_is_refused(test_db, monkeypatch):
    _seed(test_db)
    monkeypatch.setenv("YOKE_HOOK_EVENT", "PreToolUse")

    with pytest.raises(MergedAtCorrectionHookContextError):
        repair.operator_correct_landing_pull_request(
            test_db, ITEM_ID, "1276", REASON
        )


def test_a_number_that_is_not_a_pull_request_is_refused(test_db):
    _seed(test_db)

    with pytest.raises(MergedAtCorrectionError) as refusal:
        repair.operator_correct_landing_pull_request(
            test_db, ITEM_ID, "feature-branch", REASON
        )

    assert "pull request number" in str(refusal.value)
