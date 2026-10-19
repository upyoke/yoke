"""Run creation derives each project's carried work once across both passes.

Composition derives carried work for enrollment and again for the omitted-work
refusal, and creation composes twice: before the creation lock and under it.
Each derivation reads attribution row by row, so on a remote database the
repeats cost minutes. These tests count derivations against a real
two-project release.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.test_deployment_run_source_reads_once import (
    _carrier_tip,
    _release,
)
from runtime.api.fixtures.bound_source_release import CARRIER_FLOW
from runtime.api.fixtures.carried_release_candidate import insert_run
from yoke_core.domain import deployment_run_carried_work as carried_work
from yoke_core.domain import deployment_run_create_write as create_write
from yoke_core.domain.deployment_run_create_write import create_run


def _count_derivations(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, str]]:
    """Log each project comparison derived, by project and previous release."""
    derived: list[tuple[int, str]] = []
    derive = carried_work.derive_project_carried_work

    def counted(conn: Any, run_id: str, *, previous: Any, **comparison: Any):
        previous_id = str(carried_work._cell(previous, "id", 0)) if previous else ""
        derived.append((int(comparison["project_id"]), previous_id))
        return derive(conn, run_id, previous=previous, **comparison)

    monkeypatch.setattr(carried_work, "derive_project_carried_work", counted)
    return derived


def test_one_create_derives_each_project_carried_work_once(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _release(test_db, tmp_path, monkeypatch)
    derived = _count_derivations(monkeypatch)

    create_run("yoke", CARRIER_FLOW, release_lineage=_carrier_tip(release))

    # Carrier and consumer, once each: the refusal reuses enrollment's answer
    # and the locked pass reuses the unlocked pass's.
    assert len(derived) == 2
    assert len(set(derived)) == 2


def test_a_predecessor_released_before_the_lock_is_derived_again(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _release(test_db, tmp_path, monkeypatch)
    lineage = _carrier_tip(release)
    derived = _count_derivations(monkeypatch)
    validate = create_write.validate_before_lock

    def validate_then_release(*args: Any, **kwargs: Any) -> None:
        validate(*args, **kwargs)
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

    monkeypatch.setattr(create_write, "validate_before_lock", validate_then_release)

    create_run("yoke", CARRIER_FLOW, release_lineage=lineage)

    # The locked pass compares against the new predecessor, so it derives
    # every project again instead of reusing the provisional answer. Each
    # source refresh retries the pass, so a project can be asked more than
    # once; the provisional answers are derived exactly once.
    provisional = [entry for entry in derived if entry[1] != "run-released-meanwhile"]
    locked = {entry for entry in derived if entry[1] == "run-released-meanwhile"}
    assert len(provisional) == 2
    assert {project for project, _ in locked} == {project for project, _ in provisional}
