"""Browser QA capture completion hands its reviewer readable evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.domain.browser_qa_test_helpers import (
    _browser_check_steps,
    _placeholder,
    _run_scenario,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        yield path


def test_capture_completion_hands_back_ready_artifact_reads(
    tmp_path: Path, db_path: str
) -> None:
    """The capture's own scratch paths are unreadable to its reviewer.

    So completion has to name the registered ids and the command that
    turns each one back into bytes, or the reviewer starts by hunting.
    """
    _seed_item(db_path, 605)
    requirement_id = _seed_requirement(
        db_path, 605, "browser-check",
        {
            "base_url": "http://localhost:9999",
            "steps": _browser_check_steps(
                {"action": "screenshot", "capture": True, "label": "page1"},
            ),
        },
    )

    shot = tmp_path / "page1.png"
    shot.write_bytes(b"PNG")

    result = _run_scenario(
        db_path, 605,
        execute_step_responses=[
            {"success": True, "artifacts": []},
            {"success": True, "artifacts": [str(shot)]},
        ],
    )

    run = result.runs[0]
    assert run.recorded_screenshots == 1
    assert len(run.artifact_ids) == 1
    emitted = run.to_dict()
    assert emitted["artifact_ids"] == run.artifact_ids
    assert emitted["artifact_reads"] == [
        "yoke qa artifact read "
        f"--requirement-id {requirement_id} "
        f"--artifact-id {run.artifact_ids[0]}"
    ]

    conn = connect_test_db(db_path)
    marker = _placeholder(conn)
    raw = conn.execute(
        f"SELECT raw_result FROM qa_runs WHERE id={marker}",
        (run.qa_run_id,),
    ).fetchone()
    conn.close()
    recorded = json.loads(raw[0])
    assert recorded["artifact_ids"] == run.artifact_ids
    assert recorded["artifact_reads"] == emitted["artifact_reads"]
