"""A release credits an item with exactly the commits its receipt recorded.

One real repository carries a multi-commit item that synced the trunk and
landed by fast forward, the pin commit a release's own automation wrote, and a
hotfix pushed straight to the trunk whose message names that item. Stage and
production release it from different baselines, and stage releases twice.

Every commit the item contributed is the item's in whichever release first
carries it — once per environment, so a commit stage already shipped is not
stage's again while production still sees it as new. The pin stays release
output. The hotfix stays unattributed despite naming the item, and the
refusal names it by sha and subject beside the executable receipt repair.
"""

from __future__ import annotations

import subprocess
import shlex
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import item_ref, serve_repository
from runtime.api.fixtures.release_output_source import (
    EMPTY_SOURCES,
    insert_flow,
    project_slug,
)
from yoke_cli.commands.adapters import merge_receipt_commits as adapter
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_release_output_record import (
    record_release_output,
)
from yoke_core.domain.deployment_run_unattributed_commits import (
    unattributed_commits_refusal,
)
from yoke_core.domain.item_merge_commit_attestation import attest_commits
from yoke_core.domain.item_merge_contributed_commits import before_landing
from yoke_core.domain.item_merge_receipt_document import record_entry

ITEM_ID = 9711
FLOW = "contributed-commit-flow"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: Path, name: str, message: str = "") -> str:
    (repo / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", f"{name}.txt")
    _git(repo, "commit", "-m", message or name)
    return _git(repo, "rev-parse", "HEAD")


def _environment(conn: Any, name: str) -> int:
    conn.execute(
        "INSERT INTO environments(site,project_id,name,created_at) "
        "SELECT id,1,%s,'2026-09-20T00:00:00Z' FROM sites WHERE project_id=1 "
        "ORDER BY id LIMIT 1 ON CONFLICT(project_id,name) DO NOTHING",
        (name,),
    )
    row = conn.execute(
        "SELECT id FROM environments WHERE project_id=1 AND name=%s", (name,)
    ).fetchone()
    return int(row[0])


def _run(
    conn: Any,
    run_id: str,
    lineage: str,
    environment_id: int,
    *,
    status: str = "succeeded",
    completed_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "current_stage,created_at,completed_at,bound_sources,target_tier,"
        "target_environment_id) VALUES "
        "(%s,1,%s,%s,%s,'complete',%s,%s,%s,'persistent',%s)",
        (
            run_id,
            FLOW,
            lineage,
            status,
            completed_at or "2026-09-20T00:00:00Z",
            completed_at,
            EMPTY_SOURCES,
            environment_id,
        ),
    )
    conn.commit()


@pytest.fixture()
def release(test_db: Any, tmp_path: Path, monkeypatch) -> dict[str, Any]:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Yoke Test")
    _git(repo, "config", "user.email", "test@example.com")
    baseline = _commit(repo, "baseline")
    insert_item(test_db, id=ITEM_ID, project_sequence=ITEM_ID, workflow_id="dash")
    ref = item_ref(test_db, ITEM_ID)
    _git(repo, "checkout", "-q", "-b", ref)
    first, second = _commit(repo, "first"), _commit(repo, "second")
    _git(repo, "checkout", "-q", "main")
    neighbour = _commit(repo, "neighbour")
    _git(repo, "checkout", "-q", ref)
    _git(repo, "merge", "-q", "--no-edit", "--no-ff", "main")
    sync = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    record_entry(
        test_db,
        item_id=ITEM_ID,
        branch=ref,
        target="main",
        commit_sha=sync,
        contributed_commits=before_landing(str(repo), target="main", commit_sha=sync),
    )
    _git(repo, "merge", "-q", "--ff-only", ref)
    record_entry(test_db, item_id=ITEM_ID, branch=ref, target="main", merge_sha=sync)
    pin = _commit(repo, "pin", "Pin prod Yoke 0.1.1+launch.500")
    hotfix = _commit(repo, "hotfix", f"Hotfix pushed straight to main for {ref}")
    serve_repository(monkeypatch, repo)
    insert_flow(test_db, FLOW)
    stage, prod = _environment(test_db, "stage"), _environment(test_db, "prod")
    _run(test_db, "run-prod-1", baseline, prod, completed_at="2026-09-20T01:00:00Z")
    _run(test_db, "run-stage-1", baseline, stage, completed_at="2026-09-20T01:00:00Z")
    record_release_output(
        test_db,
        run_id="run-stage-1",
        project=project_slug(test_db),
        commit_sha=pin,
    )
    _run(test_db, "run-stage-2", sync, stage, completed_at="2026-09-20T02:00:00Z")
    _run(test_db, "run-stage-3", hotfix, stage, status="created")
    _run(test_db, "run-prod-2", hotfix, prod, status="created")
    test_db.commit()
    return {
        "ref": ref,
        "item": [first, second, sync],
        "neighbour": neighbour,
        "pin": pin,
        "hotfix": hotfix,
    }


def _credited(carried: dict[str, Any]) -> list[str]:
    """Every credited commit, in range order: oldest first."""
    return [sha for entry in carried["items"] for sha in entry["commit_shas"]]


def test_production_credits_every_commit_the_item_contributed(
    test_db: Any,
    release: dict[str, Any],
) -> None:
    carried = derive_carried_work(test_db, "run-prod-2")

    assert [entry["item_id"] for entry in carried["items"]] == [ITEM_ID]
    assert _credited(carried) == release["item"]
    assert release["neighbour"] not in _credited(carried) + carried["commits"]
    assert [entry["commit_sha"] for entry in carried["release_output"]] == [
        release["pin"]
    ]
    assert carried["commits"] == [release["hotfix"]]


def test_a_repeated_stage_release_does_not_count_shipped_commits_again(
    test_db: Any,
    release: dict[str, Any],
) -> None:
    shipped = derive_carried_work(test_db, "run-stage-2")
    carried = derive_carried_work(test_db, "run-stage-3")

    assert _credited(shipped) == release["item"]
    assert carried["items"] == []
    assert carried["commits"] == [release["hotfix"]]


def test_a_commit_naming_an_item_is_refused_by_sha_and_subject(
    test_db: Any,
    release: dict[str, Any],
) -> None:
    carried = derive_carried_work(test_db, "run-prod-2")

    refusal = unattributed_commits_refusal("run-prod-2", carried)

    assert f"{release['hotfix']} Hotfix pushed straight to main for" in refusal
    assert "yoke merge-receipt commits attest PREFIX-N" in refusal
    assert f"--commit {release['hotfix']}" in refusal
    assert "composition_resolution" not in refusal


def test_printed_recovery_clears_attribution_without_a_persisted_run(
    test_db: Any,
    release: dict[str, Any],
    monkeypatch,
) -> None:
    carried = derive_carried_work(test_db, "run-prod-2")
    refused_run = "run-not-created"
    carried["project"] = project_slug(test_db)
    refusal = unattributed_commits_refusal(refused_run, carried)
    assert (
        test_db.execute(
            "SELECT id FROM deployment_runs WHERE id=%s",
            (refused_run,),
        ).fetchone()
        is None
    )
    command = refusal.split("Recovery:\n", 1)[1].splitlines()[0]
    words = shlex.split(command)
    assert words[:4] == ["yoke", "merge-receipt", "commits", "attest"]
    assert words[4] == "PREFIX-N"
    words[4] = release["ref"]
    words[-1] = "the item's follow-up, pushed without a lane"

    def dispatch_repair(**kwargs):
        assert kwargs["function_id"] == "merge_receipt.commits.attest"
        assert kwargs["target"].public_ref == release["ref"]
        assert kwargs["target"].project_id == carried["project"]
        attest_commits(test_db, item_id=ITEM_ID, **kwargs["payload"])
        test_db.commit()
        return 0

    monkeypatch.setattr(adapter, "dispatch_and_emit", dispatch_repair)
    assert adapter.merge_receipt_commits_attest(words[4:]) == 0

    carried = derive_carried_work(test_db, "run-prod-2")

    assert _credited(carried) == [*release["item"], release["hotfix"]]
    assert carried["commits"] == []
    assert unattributed_commits_refusal("run-prod-2", carried) == ""


def test_recovery_fills_every_offending_sha_and_quotes_project() -> None:
    shas = ["a" * 40, "b" * 40]
    project = "project with spaces"
    refusal = unattributed_commits_refusal(
        "missing-run",
        {
            "commits": shas,
            "project": project,
        },
    )
    words = shlex.split(refusal.split("Recovery:\n", 1)[1].splitlines()[0])
    assert [words[i + 1] for i, word in enumerate(words) if word == "--commit"] == shas
    assert words[words.index("--project") + 1] == project
