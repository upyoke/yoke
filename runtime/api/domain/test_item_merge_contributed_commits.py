"""A landing's receipt names every commit the item put on its target.

Each case builds a real repository in the shape a landing leaves: a fast
forward of a multi-commit branch, a branch that synced its target before
fast-forwarding, a true merge commit, and a sync that pulled in somebody
else's unlanded branch. The contribution is the item's own first-parent line
and nothing a sync brought in.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.item_merge_commit_attestation import (
    CommitAttestationRefused,
    attest_commits,
)
from yoke_core.domain.item_merge_contributed_commits import (
    after_landing,
    before_landing,
)
from yoke_core.domain.item_merge_receipt_document import (
    merge_identities,
    record_entry,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", f"{name}.txt")
    _git(repo, "commit", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "project"
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Yoke Test")
    _git(path, "config", "user.email", "test@example.com")
    _commit(path, "baseline")
    return path


def _branch_with(repo: Path, branch: str, *names: str) -> list[str]:
    _git(repo, "checkout", "-q", "-b", branch, "main")
    shas = [_commit(repo, name) for name in names]
    _git(repo, "checkout", "-q", "main")
    return shas


def test_a_multi_commit_branch_contributes_each_of_its_commits(repo: Path) -> None:
    item = _branch_with(repo, "item", "first", "second", "third")

    contributed = before_landing(str(repo), target="main", commit_sha=item[-1])

    assert contributed == tuple(reversed(item))


def test_a_synced_then_fast_forwarded_branch_excludes_what_the_sync_brought(
    repo: Path,
) -> None:
    item = _branch_with(repo, "item", "first", "second")
    neighbour = _commit(repo, "neighbour-landed")
    _git(repo, "checkout", "-q", "item")
    _git(repo, "merge", "-q", "--no-edit", "--no-ff", "main")
    sync = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")

    before = before_landing(str(repo), target="main", commit_sha=sync)
    _git(repo, "merge", "-q", "--ff-only", "item")
    after = after_landing(str(repo), commit_sha=item[-1], merge_sha=sync)

    assert before == (sync, *reversed(item))
    assert after == tuple(reversed(item))
    assert neighbour not in before and neighbour not in after


def test_a_landing_merge_commit_contributes_its_branch_side(repo: Path) -> None:
    item = _branch_with(repo, "item", "first", "second")
    neighbour = _commit(repo, "neighbour-landed")
    _git(repo, "merge", "-q", "--no-edit", "--no-ff", "item")
    landing = _git(repo, "rev-parse", "HEAD")

    contributed = after_landing(str(repo), commit_sha=item[-1], merge_sha=landing)

    assert contributed == tuple(reversed(item))
    assert neighbour not in contributed


def test_a_sync_of_an_unlanded_branch_contributes_none_of_its_commits(
    repo: Path,
) -> None:
    other = _branch_with(repo, "other", "other-work")
    item = _branch_with(repo, "item", "first")
    _git(repo, "checkout", "-q", "item")
    _git(repo, "merge", "-q", "--no-edit", "other")
    tip = _commit(repo, "second")
    _git(repo, "checkout", "-q", "main")

    contributed = before_landing(str(repo), target="main", commit_sha=tip)

    assert other[0] not in contributed
    assert item[0] in contributed and tip in contributed


def test_a_fast_forward_leaves_nothing_to_derive_after_landing(repo: Path) -> None:
    item = _branch_with(repo, "item", "only")
    _git(repo, "merge", "-q", "--ff-only", "item")

    assert after_landing(str(repo), commit_sha=item[0], merge_sha=item[0]) == ()


def test_an_empty_write_keeps_the_contribution_recorded_before_the_merge(
    test_db: Any,
) -> None:
    insert_item(test_db, id=9701, project_sequence=9701, workflow_id="dash")
    record_entry(
        test_db, item_id=9701, branch="lane", target="main",
        commit_sha="c" * 40, contributed_commits=["a" * 40, "c" * 40],
    )
    entry = record_entry(
        test_db, item_id=9701, branch="lane", target="main", merge_sha="m" * 40,
    )

    assert entry["contributed_commits"] == ["a" * 40, "c" * 40]
    assert ("a" * 40) in {sha for _item, sha in merge_identities(test_db, 1)}


def test_an_attested_commit_is_credited_to_the_item(test_db: Any) -> None:
    insert_item(test_db, id=9702, project_sequence=9702, workflow_id="dash")
    record_entry(
        test_db, item_id=9702, branch="lane", target="main",
        commit_sha="c" * 40, merge_sha="d" * 40,
    )

    result = attest_commits(
        test_db, item_id=9702, commits=["E" * 40, "c" * 40],
        reason="earlier commits of this landing",
    )

    assert result["attested"] == ["e" * 40]
    assert result["already_recorded"] == ["c" * 40]
    assert (9702, "e" * 40) in set(merge_identities(test_db, 1))


@pytest.mark.parametrize(
    ("commits", "reason", "code"),
    [
        (["abc1234"], "why", "commit_sha_not_full"),
        (["e" * 40], "  ", "reason_required"),
    ],
)
def test_an_attestation_refuses_what_it_cannot_record(
    test_db: Any, commits: list[str], reason: str, code: str,
) -> None:
    insert_item(test_db, id=9703, project_sequence=9703, workflow_id="dash")
    record_entry(
        test_db, item_id=9703, branch="lane", target="main",
        commit_sha="c" * 40, merge_sha="d" * 40,
    )

    with pytest.raises(CommitAttestationRefused) as refused:
        attest_commits(test_db, item_id=9703, commits=commits, reason=reason)

    assert refused.value.code == code


def test_an_item_that_never_landed_has_nothing_to_attest_to(test_db: Any) -> None:
    insert_item(test_db, id=9704, project_sequence=9704, workflow_id="dash")
    record_entry(
        test_db, item_id=9704, branch="lane", target="main", commit_sha="c" * 40,
    )

    with pytest.raises(CommitAttestationRefused) as refused:
        attest_commits(test_db, item_id=9704, commits=["e" * 40], reason="why")

    assert refused.value.code == "no_landed_receipt"
    assert "yoke merge item" in str(refused.value)
