# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from typing import Any

import pytest

from runtime.api.domain.deployment_membership_round_trips_test_support import (
    _admit_all,
    _created_run,
    _members,
    _statements,
)

from runtime.api.domain.deployment_run_start_lock_window_test_support import (
    _MEMBER_READERS,
    LARGE,
    SMALL,
    _known_carried,
    _land_before_the_lock,
    _Recorder,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.bound_source_release import (
    CARRIER_FLOW,
    two_project_release,
)

from runtime.api.fixtures.carried_release_candidate import git

from yoke_core.domain import deployment_run_carried_membership as carried_membership

from yoke_core.domain.deployment_run_bound_source_prepare import prepare_bound_sources

from yoke_core.domain.deployment_run_bound_sources import record_bound_sources

from yoke_core.domain.deployment_runs_validation import cmd_validate_composition

from yoke_core.domain.schema_read_scope import composition_reads


def _carrying_run(conn: Any, name: str, carried: list[int]) -> str:
    """A created run whose recorded carried work names *carried*, unenrolled."""
    run_id = _created_run(conn, name, carried)
    record_bound_sources(conn, run_id)
    conn.execute(
        "UPDATE deployment_runs SET carried_work=%s WHERE id=%s",
        (json.dumps(_known_carried(carried)), run_id),
    )
    conn.commit()
    return run_id


def _validate(conn: Any, run_id: str) -> tuple[tuple[bool, str], _Recorder]:
    recorder = _Recorder(conn)
    with composition_reads():
        verdict = cmd_validate_composition(run_id, connection=recorder)
    conn.commit()
    return verdict, recorder
