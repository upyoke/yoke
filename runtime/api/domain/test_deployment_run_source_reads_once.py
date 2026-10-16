"""Run creation and execution context read each repository source once.

Composition validation resolves bound branches and walks commit ranges. Held
under the global creation lock, those reads queued every concurrent create
behind one another; read twice per operation, they doubled that wait. These
tests count the reads against a real two-project release and prove the
creation lock only covers the database re-check.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from runtime.api.fixtures.bound_source_release import (
    CARRIER_FLOW,
    CARRIER_ITEM_ID,
    CONSUMER_ITEM_ID,
    two_project_release,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import insert_run
from yoke_core.domain import deploy_pipeline_github_workflow_bindings as branch_reads
from yoke_core.domain import deployment_run_create_idempotency as idempotency
from yoke_core.domain import deployment_run_create_write as create_write
from yoke_core.domain import deployment_run_carried_work_sources as carried_sources
from yoke_core.domain.deployment_prepared_source import PreparedSource
from yoke_core.domain.deployment_source_reads import prepared_sources_only
from yoke_core.domain.schema_read_scope import composition_reads
from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource
from yoke_core.domain.deployment_run_create_write import CreatedRun, create_run
from yoke_core.domain.handlers import deployment_run_execution as execution
from yoke_contracts.api.function_call import TargetRef


def _release(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    test_db.execute(
        "UPDATE deployment_flows SET status='active' WHERE id=%s", (CARRIER_FLOW,)
    )
    test_db.execute("DELETE FROM deployment_runs WHERE id='run-candidate'")
    test_db.commit()
    return release


def _carrier_tip(release: dict[str, Any]) -> str:
    from runtime.api.fixtures.carried_release_candidate import git

    return git(release["carrier_repo"], "rev-parse", "HEAD").strip()


def _record_reads(
    monkeypatch: pytest.MonkeyPatch, *, before_lock=None, branch_read=None
) -> list[str]:
    """Log each repository read, and the moment the creation lock is taken."""
    reads: list[str] = []
    resolve = branch_reads.resolve_branch_head_sha
    compare = LocalCheckoutSource.commit_range
    validate = create_write.validate_before_lock

    def resolve_head(*args: Any, **kwargs: Any):
        reads.append("branch_head")
        if branch_read is not None:
            branch_read()
        return resolve(*args, **kwargs)

    def commit_range(self, base: str, head: str):
        reads.append("commit_range")
        return compare(self, base, head)

    def validate_then_lock(*args: Any, **kwargs: Any) -> None:
        validate(*args, **kwargs)
        if before_lock is not None:
            before_lock()
        reads.append("lock")

    monkeypatch.setattr(branch_reads, "resolve_branch_head_sha", resolve_head)
    monkeypatch.setattr(LocalCheckoutSource, "commit_range", commit_range)
    monkeypatch.setattr(create_write, "validate_before_lock", validate_then_lock)
    return reads


def _members(conn: Any, run_id: str) -> set[int]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (run_id,)
    ).fetchall()
    return {int(row[0]) for row in rows}


def test_one_create_reads_each_source_once_and_nothing_under_the_lock(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _release(test_db, tmp_path, monkeypatch)
    reads = _record_reads(monkeypatch)

    created = create_run("yoke", CARRIER_FLOW, release_lineage=_carrier_tip(release))

    # One bound branch, and one comparison per shipped project (carrier and
    # consumer), all before the lock; the locked re-check reuses them.
    assert reads == ["branch_head", "commit_range", "commit_range", "lock"]
    bound = json.loads(
        test_db.execute(
            "SELECT bound_sources FROM deployment_runs WHERE id=%s",
            (created.run_id,),
        ).fetchone()[0]
    )
    assert bound["inputs"] == {"consumer_sha": release["consumer_tip"]}
    assert _members(test_db, created.run_id) == {CARRIER_ITEM_ID, CONSUMER_ITEM_ID}
    unlocked = test_db.execute(
        "SELECT count(*) FROM deployment_runs WHERE id LIKE 'run-unlocked-%'"
    ).fetchone()[0]
    assert unlocked == 0


def test_concurrent_keyed_creates_read_together_then_replay_under_the_lock(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _release(test_db, tmp_path, monkeypatch)
    lineage = _carrier_tip(release)
    # Each create must reach its branch read while the other is also there.
    # A read held under the creation lock would leave the second create
    # waiting on the lock, and this barrier would break.
    together = threading.Barrier(2, timeout=60)
    _record_reads(monkeypatch, branch_read=together.wait)
    request = idempotency.canonical_request(
        {"flow": CARRIER_FLOW, "release_lineage": lineage}
    )
    created: list[CreatedRun] = []
    failures: list[BaseException] = []

    def create() -> None:
        try:
            created.append(
                create_run(
                    "yoke",
                    CARRIER_FLOW,
                    release_lineage=lineage,
                    idempotency_key="paired-release",
                    create_request=request,
                )
            )
        except BaseException as exc:  # noqa: BLE001 - reported by the assert
            failures.append(exc)

    threads = [threading.Thread(target=create) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert failures == []
    # Both validated before either held the lock; under it, the later create
    # finds the key the earlier one committed and returns that run.
    assert {run.run_id for run in created} == {created[0].run_id}
    assert sorted(run.replayed for run in created) == [False, True]
    count = test_db.execute(
        "SELECT count(*) FROM deployment_runs WHERE create_idempotency_key=%s",
        ("paired-release",),
    ).fetchone()[0]
    assert count == 1


def test_a_predecessor_released_before_the_lock_is_compared_again(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _release(test_db, tmp_path, monkeypatch)
    lineage = _carrier_tip(release)

    def release_carrier_tip() -> None:
        insert_run(
            test_db,
            "run-released-meanwhile",
            lineage=lineage,
            status="succeeded",
            flow=CARRIER_FLOW,
            bound_sources=json.dumps(
                {
                    "schema": 1,
                    "projects": [
                        {
                            "project": "consumer",
                            "project_id": release["consumer_id"],
                            "commit_sha": release["consumer_tip"],
                        }
                    ],
                    "inputs": {"consumer_sha": release["consumer_tip"]},
                }
            ),
            completed_at="2026-09-15T00:00:00Z",
        )

    reads = _record_reads(monkeypatch, before_lock=release_carrier_tip)

    created = create_run("yoke", CARRIER_FLOW, release_lineage=lineage)

    locked_reads = reads[reads.index("lock") + 1 :]
    # The basis moved, so the cached comparisons no longer apply; the bound
    # branch head stays the one this operation already pinned.
    assert "commit_range" in locked_reads
    assert "branch_head" not in locked_reads
    assert created.replayed is False


def test_execution_context_resolves_each_bound_branch_once(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _release(test_db, tmp_path, monkeypatch)
    run_id = create_run(
        "yoke", CARRIER_FLOW, release_lineage=_carrier_tip(release)
    ).run_id
    # Creation pinned this run's bound sources; a start that finds none
    # recorded is the case that has to resolve them.
    test_db.execute(
        "UPDATE deployment_runs SET bound_sources=NULL WHERE id=%s", (run_id,)
    )
    test_db.commit()
    reads = _record_reads(monkeypatch)
    monkeypatch.setattr(execution, "require_run_driver", lambda *_args: None)

    outcome = execution.handle_deployment_execution_context(
        deployment_request(
            function="deployment_runs.execution.context",
            target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        )
    )

    assert outcome.primary_success, outcome.error
    assert reads.count("branch_head") == 1
    # Enrollment and the membership refusal share one comparison per project.
    assert reads.count("commit_range") == 2
    assert outcome.result_payload["run"]["bound_sources"]["inputs"] == {
        "consumer_sha": release["consumer_tip"]
    }


LANDED_AT = "2026-10-16T15:00:00Z"


class _Lanes:
    origin, location = "checkout", "/repo"

    def __init__(self) -> None:
        self.batches: list[tuple[str, ...]] = []

    def resolve_commits(self, refs) -> dict[str, str]:
        self.batches.append(tuple(refs))
        return {ref: ref if ref.startswith("sha-") else "" for ref in refs}

    def carrying_commit(self, lane_commit, *, base, head, commits):
        return ""

    def commit_time(self, sha: str) -> None:
        return None

    def warnings(self) -> list:
        return []


def test_locked_validation_reading_lanes_in_another_order_asks_nothing_new(
    test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    for item_id in (1, 2, 3, 4):
        insert_item(test_db, id=item_id, status="done", merged_at=LANDED_AT)
        # Even items record a sha the source lacks, so their branch is asked.
        sha = f"sha-{item_id}" if item_id % 2 else f"gone-{item_id}"
        test_db.execute(
            "INSERT INTO item_worktrees (item_id, branch, path, lane_role, state, "
            "commit_sha, created_at, updated_at) VALUES (%s, %s, NULL, "
            "'implementation', 'active', %s, now(), now())",
            (item_id, f"YOK-{item_id}", sha),
        )
    real_rows = carried_sources._safe_rows
    reverse = {"lanes": False}

    def rows(conn, sql, *args, **kwargs):
        found = real_rows(conn, sql, *args, **kwargs)
        flip = reverse["lanes"] and "item_worktrees" in sql
        return list(reversed(found)) if flip else found

    monkeypatch.setattr(carried_sources, "_safe_rows", rows)
    project_id = int(
        test_db.execute("SELECT id FROM projects WHERE slug='yoke'").fetchone()[0]
    )
    lanes = _Lanes()

    def derive() -> None:
        carried_sources.resolve_carried_items(
            test_db,
            project_id=project_id,
            source=source,
            base="base",
            head="head",
            commits=["d" * 40],
        )

    with composition_reads():
        source = PreparedSource(test_db, ("carried_source", project_id, ""), lanes)
        derive()
        reverse["lanes"] = True
        with prepared_sources_only():
            derive()
    assert lanes.batches == [
        ("gone-2", "gone-4", "sha-1", "sha-3"),
        ("YOK-2", "YOK-4"),
    ]
