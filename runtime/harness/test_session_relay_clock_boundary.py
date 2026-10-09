"""Relay adapter context projects only its owned launch deadline clock."""

from datetime import datetime

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_harness.session_relay_runtime import execution_context


@pytest.mark.parametrize(
    "deadline",
    [
        "2026-10-09T20:00:00.123456Z",
        "2026-10-10T01:45:00.123456+05:45",
        parse_instant("2026-10-09T20:00:00.123456Z"),
    ],
)
def test_launch_deadline_projects_fixed_six_utc(tmp_path, deadline):
    opaque = "2026-10-10T01:45:00.123456+05:45 unchanged"
    job = {
        "project_id": 1,
        "target_workspace": str(tmp_path),
        "deadline_at": deadline,
        "native_instruction": opaque,
    }
    context = execution_context(job)
    assert context.launch_deadline_at == "2026-10-09T20:00:00.123456Z"
    assert context.native_instruction == opaque and job["deadline_at"] == deadline


@pytest.mark.parametrize("job_extra", [{}, {"deadline_at": None}])
def test_absent_launch_deadline_stays_null(tmp_path, job_extra):
    context = execution_context(
        {"project_id": 1, "target_workspace": str(tmp_path), **job_extra}
    )
    assert context.launch_deadline_at is None


@pytest.mark.parametrize(
    "deadline",
    [
        "",
        "2026-10-09",
        "2026-10-09T20:00:00",
        "2026-10-09 20:00:00+00",
        datetime(2026, 10, 9),
        0,
    ],
)
def test_invalid_present_launch_deadline_refuses(tmp_path, deadline):
    with pytest.raises(InvalidInstant):
        execution_context(
            {
                "project_id": 1,
                "target_workspace": str(tmp_path),
                "deadline_at": deadline,
            }
        )
