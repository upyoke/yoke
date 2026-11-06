"""One run evaluation resolves the candidate's pinned Yoke release once.

Every member of a run shares the deployed commit, so the release it pins and
whether the installer origin publishes it are one answer per evaluation, not
one network round trip per member.
"""

from __future__ import annotations

from runtime.api.domain.deployment_qa_pinned_release_reads_test_support import (
    BASE_URL as BASE_URL,
    LINEAGE as LINEAGE,
    MEMBERS as MEMBERS,
    PINNED as PINNED,
    PIN_FILE as PIN_FILE,
    RUN as RUN,
    _count_release_reads as _count_release_reads,
    _seed as _seed,
)


import time
from datetime import datetime, timezone
from typing import Any

from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
)
from yoke_core.domain import deployment_qa_stage_outstanding as outstanding
from yoke_core.domain.deployment_run_auto_completion import _readiness
from yoke_core.domain.deployment_runs_crud_mutate import cmd_remove_item
from yoke_core.domain.post_deploy_verification_answer import (
    NOT_REQUIRED,
    PostDeployAnswer,
)
from yoke_core.domain.steering_fleet_report_run_progress import run_progress


def test_one_stage_evaluation_resolves_the_pinned_release_once(test_db, monkeypatch):
    _seed(test_db)
    counts = _count_release_reads(monkeypatch)

    result = outstanding.qa_stage_outstanding(
        test_db, run_id=RUN, stage_name=ITEM_QA_STAGE
    )

    assert result is not None and result.subjects == len(MEMBERS)
    assert result.waiting == len(MEMBERS)
    assert counts == {"pin_file": 1, "published": 1}


def test_one_report_resolves_the_pinned_release_once(test_db, monkeypatch):
    _seed(test_db)
    counts = _count_release_reads(monkeypatch)

    (progress,) = [
        run
        for run in run_progress(test_db, project_id=1, now=datetime.now(timezone.utc))
        if run.run_id == RUN
    ]

    assert progress.outstanding == len(MEMBERS)
    assert counts == {"pin_file": 1, "published": 1}


def test_exempt_member_never_resolves_its_execution_target(test_db, monkeypatch):
    _seed(test_db)

    def exempt(conn: Any, subject: Any) -> PostDeployAnswer:
        return PostDeployAnswer(NOT_REQUIRED, ("owes only another target",))

    def unreachable(conn: Any, subject: Any, **_: Any) -> dict:
        raise AssertionError("an exempt member resolved its execution target")

    monkeypatch.setattr(outstanding, "member_post_deploy_answer", exempt)
    monkeypatch.setattr(outstanding, "deployment_qa_execution_target", unreachable)

    result = outstanding.qa_stage_outstanding(
        test_db, run_id=RUN, stage_name=ITEM_QA_STAGE
    )

    assert result is not None and result.waiting == 0
    assert len(result.no_obligation_lines) == len(MEMBERS)


def test_first_waiting_member_ends_a_readiness_walk(test_db, monkeypatch):
    _seed(test_db)
    _count_release_reads(monkeypatch)
    evaluated: list[int | None] = []
    member_lines = outstanding._member_lines

    def counted(conn: Any, **kwargs: Any) -> tuple[list[str], list[str]]:
        evaluated.append(kwargs["member"])
        return member_lines(conn, **kwargs)

    monkeypatch.setattr(outstanding, "_member_lines", counted)
    release_seeded_driver(test_db, RUN)

    ready, reason = _readiness(test_db, RUN)

    assert ready is None
    assert reason == f"QA stage {ITEM_QA_STAGE!r} is not fully accepted"
    assert evaluated == [MEMBERS[0]]


def test_removing_a_member_from_a_large_executing_run_stays_fast(test_db, monkeypatch):
    _seed(test_db)
    counts = _count_release_reads(monkeypatch)
    release_seeded_driver(test_db, RUN)

    started = time.monotonic()
    message = cmd_remove_item(
        RUN, MEMBERS[-1], reason="rides the next release", session_id="s", actor_id=1
    )
    elapsed = time.monotonic() - started

    assert "is not fully accepted" in message
    assert elapsed < 5, f"remove-item took {elapsed:.1f}s on {len(MEMBERS)} members"
    assert counts == {"pin_file": 1, "published": 1}
