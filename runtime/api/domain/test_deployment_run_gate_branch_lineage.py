"""Gate-branch release lineage: comparisons that fail closed, and checkout ancestry."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import deployment_run_ci_tested_source as tested
from yoke_core.domain import deployment_run_gate_branch_lineage as lineage
from yoke_core.domain.deployment_run_carried_membership_refusal import (
    _compared_lineages,
)
from yoke_core.domain.deployment_run_carried_work_source import (
    ANCESTRY_UNREADABLE,
    RELATION_AHEAD,
    RELATION_DIVERGED,
    CarriedWorkSourceUnavailable,
    LocalCheckoutSource,
)
from yoke_core.domain.gh_rest_transport import RestTransportError

PREVIOUS, SELECTED = "a" * 40, "c" * 40
TARGET = tested.CiGateTarget(
    project="platform",
    flow="flow",
    repo="owner/platform",
    workflow="platform-ci.yml",
    branch="main",
    token="token",
    environment="prod",
)
REST = "yoke_core.domain.github_actions_rest"


def test_compare_reads_the_previous_release_against_the_selection():
    with mock.patch(f"{REST}.rest_get", return_value={"status": "ahead"}) as read:
        assert lineage._compare_status(TARGET, PREVIOUS, SELECTED) == "ahead"

    assert read.call_args.args[0] == (
        f"/repos/owner/platform/compare/{PREVIOUS}...{SELECTED}"
    )
    assert read.call_args.kwargs["token"] == "token"


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (RestTransportError("connection reset"), "connection reset"),
        (None, f"Recovery: confirm {PREVIOUS} exists in owner/platform"),
        ({"message": "Not Found"}, "gave no comparison"),
    ],
)
def test_an_unreadable_comparison_fails_closed(answer, expected):
    kwargs = (
        {"side_effect": answer}
        if isinstance(answer, Exception)
        else {"return_value": answer}
    )
    with (
        mock.patch(f"{REST}.rest_get", **kwargs),
        pytest.raises(tested.ReleaseSourceRefused) as refused,
    ):
        lineage._compare_status(TARGET, PREVIOUS, SELECTED)

    assert refused.value.code == tested.UNVERIFIABLE
    assert expected in str(refused.value)


def test_a_listing_without_parents_is_just_its_tip():
    assert lineage.first_parent_line([{"sha": SELECTED}, {"sha": PREVIOUS}]) == [
        SELECTED
    ]
    assert lineage.first_parent_line(None) == []


def test_a_blocker_names_the_two_commits_it_compared():
    named = _compared_lineages(
        {
            "previous_release_lineage": PREVIOUS,
            "previous_run_id": "run-9",
            "release_lineage": SELECTED,
        }
    )

    assert (
        named == f" (previous release {PREVIOUS} shipped by run-9; this run {SELECTED})"
    )
    assert _compared_lineages({"release_lineage": SELECTED}) == ""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def forked_checkout(tmp_path: Path) -> tuple[Path, str, str, str]:
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "trunk")
    trunk = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "side", base)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "side")
    side = _git(repo, "rev-parse", "HEAD")
    return repo, base, trunk, side


def test_checkout_relation_reads_ancestry_and_divergence(forked_checkout):
    repo, base, trunk, side = forked_checkout
    source = LocalCheckoutSource(str(repo))

    assert source.lineage_relation(base, trunk) == RELATION_AHEAD
    assert source.lineage_relation(trunk, side) == RELATION_DIVERGED


def test_checkout_relation_that_git_cannot_read_is_not_divergence(forked_checkout):
    repo, base, _trunk, _side = forked_checkout
    missing = "f" * 40
    source = LocalCheckoutSource(str(repo))

    with pytest.raises(CarriedWorkSourceUnavailable) as unavailable:
        source.lineage_relation(base, missing)

    assert unavailable.value.reason == ANCESTRY_UNREADABLE
    assert f"git merge-base --is-ancestor {base} {missing} failed" in (
        unavailable.value.recovery
    )
    assert "Divergence was not decided" in unavailable.value.recovery


def test_previous_release_is_the_newest_succeeded_run_for_the_environment(test_db):
    test_db.execute(
        "INSERT INTO deployment_flows("
        "id,project_id,name,description,stages,created_at,status) "
        "VALUES ('lineage-flow',1,'Lineage','','[]','2026-08-30T00:00:00Z','active')"
    )
    for run_id, sha, status, completed in (
        ("run-lineage-1", PREVIOUS, "succeeded", "2026-08-30T00:02:00Z"),
        ("run-lineage-2", "b" * 40, "succeeded", "2026-08-30T00:04:00Z"),
        ("run-lineage-3", SELECTED, "failed", "2026-08-30T00:06:00Z"),
    ):
        test_db.execute(
            "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,"
            "status,current_stage,created_at,completed_at) "
            "VALUES (%s,1,'lineage-flow',%s,%s,'done',%s,%s)",
            (run_id, sha, status, completed, completed),
        )
    test_db.commit()
    slug = test_db.execute("SELECT slug FROM projects WHERE id=1").fetchone()[0]

    assert lineage.previous_release(slug, "") == ("run-lineage-2", "b" * 40)
    assert lineage.previous_release(slug, "prod") is None
