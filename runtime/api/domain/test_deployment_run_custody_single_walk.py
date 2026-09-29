"""Composition asks candidate custody once, and never behind the run row lock.

Custody is a question about commits, so answering it reaches the project's
source: a containment walk per carried project, with no bound of its own. Four
composition readers need that answer, and asking each of them to fetch it put
three walks *after* enrollment had taken the run row -- a network round trip
inside a ``FOR UPDATE`` on ``deployment_runs``. A client that hibernated inside
one of those walks left the row pinned until a human terminated its backend,
and every later driver heartbeat queued silently behind it.

One walk, before any lock, handed to every reader. Custody is asked with this
run excluded, so the run enrolling its own members cannot invalidate it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    item_ref,
    record_landing_receipt,
    release_repository,
    serve_repository,
    stage_environment,
)
from yoke_core.domain import deployment_run_carried_membership as enrollment
from yoke_core.domain import deployment_run_unheld_candidates as unheld
from yoke_core.domain.deployment_run_candidate_containment import (
    CandidateContainment,
)
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
from yoke_core.domain.flow_create import cmd_create

CANDIDATE_FLOW = "custody-walk-candidate-flow"
RELEASE_STAGES = json.dumps(
    [
        {
            "name": "stage",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        }
    ]
)
LANDED_ITEM_ID = 9741


def _candidate_with_one_carried_landing(
    conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """A created run whose pinned lineage carries one delivery-ready landing."""
    insert_item(
        conn,
        id=LANDED_ITEM_ID,
        project_sequence=LANDED_ITEM_ID,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=CANDIDATE_FLOW,
        merged_at="2026-09-14T00:10:00Z",
    )
    conn.commit()
    ref = item_ref(conn, LANDED_ITEM_ID)
    repo, baseline, landing = release_repository(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    record_landing_receipt(conn, LANDED_ITEM_ID, branch=ref, tip=landing)
    stage_environment(conn)
    cmd_create(
        conn, CANDIDATE_FLOW, "yoke", CANDIDATE_FLOW, "", RELEASE_STAGES,
        status="disabled",
    )
    insert_run(
        conn, "run-previous", lineage=baseline, status="succeeded",
        flow=CANDIDATE_FLOW,
    )
    insert_run(
        conn, "run-candidate", lineage=landing, status="created", flow=CANDIDATE_FLOW,
    )
    environment = conn.execute(
        "SELECT id FROM environments WHERE project_id=1 ORDER BY id LIMIT 1"
    ).fetchone()[0]
    for run_id in ("run-previous", "run-candidate"):
        conn.execute(
            "UPDATE deployment_runs SET target_tier='persistent',"
            "target_environment_id=%s WHERE id=%s",
            (environment, run_id),
        )
    conn.commit()
    return ref


def _trace_containment_against_the_run_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    """Record containment walks and run-row locks in the order they happen."""
    trace: list[str] = []

    real_contains = CandidateContainment.contains

    def traced_contains(self, commit_sha):
        trace.append("containment")
        return real_contains(self, commit_sha)

    real_lock = enrollment.lock_run

    def traced_lock(conn, run_id):
        trace.append("lock_run")
        return real_lock(conn, run_id)

    monkeypatch.setattr(CandidateContainment, "contains", traced_contains)
    monkeypatch.setattr(enrollment, "lock_run", traced_lock)
    return trace


def test_no_containment_walk_happens_while_the_run_row_is_locked(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _candidate_with_one_carried_landing(test_db, tmp_path, monkeypatch)
    trace = _trace_containment_against_the_run_lock(monkeypatch)

    ok, message = cmd_validate_composition("run-candidate")

    assert ok is True, message
    assert ref in message
    # Both really happened, so the ordering assertion below is about real work.
    assert "containment" in trace
    assert "lock_run" in trace
    assert "containment" not in trace[trace.index("lock_run") :]


def test_candidate_custody_is_walked_once_per_validation(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four readers, one answer: enrollment, two refusals, and the skip notice."""
    _candidate_with_one_carried_landing(test_db, tmp_path, monkeypatch)
    walks: list[str] = []
    real_custody = unheld.candidate_custody

    def counted(conn, run_id):
        walks.append(run_id)
        return real_custody(conn, run_id)

    monkeypatch.setattr(unheld, "candidate_custody", counted)

    ok, message = cmd_validate_composition("run-candidate")

    assert ok is True, message
    assert walks == ["run-candidate"]
