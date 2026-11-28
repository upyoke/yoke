"""A resumed apply report carries receipts by action and target, not ordinal.

A retry rebuilds the Review plan (YOK-5780): steps the first pass finished can
drop out or change, which renumbers every later ``step_id``. The old ordinal
match lost a shifted step's receipt and gave a different target at the same
ordinal the old target's done status (feedback 99011). Earlier receipts no
current row continues stay after the current rows as history and are never
updated as current progress.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.config import onboard_apply_late_steps, onboard_apply_report


@pytest.fixture(autouse=True)
def machine_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))


def _preview(*steps: tuple[str, str]) -> dict:
    return {"plan": {"steps": [{"action": a, "target": t} for a, t in steps]}}


def _first_pass(*steps: tuple[str, str], done: int) -> dict:
    writer = onboard_apply_report.ApplyReportWriter.start(_preview(*steps), {})
    for action, target in steps[:done]:
        writer.step_started(action, target)
        writer.step_done(action, target)
    writer.fail(RuntimeError("access denied writing AGENTS.md"))
    return json.loads(writer.path.read_text())


def _resume(previous: dict, *steps: tuple[str, str]):
    return onboard_apply_report.ApplyReportWriter.start(
        _preview(*steps),
        {"resume_run_id": previous["run_id"], "resume_payload": previous},
    )


def _rows(writer) -> list[tuple[str, str, str, str]]:
    return [
        (row["step_id"], row["action"], row["target"], row["status"])
        for row in writer.payload["steps"]
    ]


def test_a_shifted_step_keeps_its_own_receipt() -> None:
    previous = _first_pass(
        ("install-yoke-global-skill", "~/.agents/skills/yoke-global"),
        ("project-create", "demo"),
        ("project-checkout-register", "/code/demo"),
        ("project-install-scaffold", ""),
        done=3,
    )
    registered = previous["steps"][2]

    # The skill is installed now, so the retry's plan no longer lists it.
    resumed = _resume(
        previous,
        ("project-create", "demo"),
        ("project-checkout-register", "/code/demo"),
        ("project-install-scaffold", ""),
    )

    rows = _rows(resumed)
    assert rows[:3] == [
        ("00-project-create", "project-create", "demo", "done"),
        ("01-project-checkout-register", "project-checkout-register", "/code/demo", "done"),
        ("02-project-install-scaffold", "project-install-scaffold", "", "pending"),
    ]
    kept = resumed.payload["steps"][1]
    assert (kept["started_at"], kept["finished_at"]) == (
        registered["started_at"],
        registered["finished_at"],
    )


def test_a_different_target_at_the_same_ordinal_inherits_nothing() -> None:
    previous = _first_pass(
        ("project-checkout-register", "/code/old"),
        ("project-install-scaffold", ""),
        done=1,
    )

    resumed = _resume(
        previous,
        ("project-checkout-register", "/code/new"),
        ("project-install-scaffold", ""),
    )

    current = resumed.payload["steps"][0]
    assert (current["step_id"], current["target"], current["status"]) == (
        "00-project-checkout-register",
        "/code/new",
        "pending",
    )
    assert current["started_at"] is None and current["finished_at"] is None
    assert _rows(resumed)[2:] == [
        (
            "prior-00-project-checkout-register",
            "project-checkout-register",
            "/code/old",
            "done",
        )
    ]


def test_a_removed_earlier_row_stays_as_history_after_the_current_rows() -> None:
    previous = _first_pass(
        ("install-yoke-global-skill", "~/.agents/skills/yoke-global"),
        ("project-install-scaffold", ""),
        done=1,
    )
    receipt = previous["steps"][0]

    resumed = _resume(previous, ("project-install-scaffold", ""))

    rows = resumed.payload["steps"]
    assert [row["step_id"] for row in rows] == [
        "00-project-install-scaffold",
        "prior-00-install-yoke-global-skill",
    ]
    assert {k: v for k, v in rows[1].items() if k != "step_id"} == {
        k: v for k, v in receipt.items() if k != "step_id"
    }


def test_history_is_never_updated_as_current_progress() -> None:
    previous = _first_pass(
        ("install-yoke-global-skill", "~/.agents/skills/yoke-global"),
        ("project-write-board-art", ""),
        done=2,
    )
    resumed = _resume(previous, ("project-install-scaffold", ""))
    history = [dict(row) for row in resumed.payload["steps"][1:]]

    resumed.step_started("install-yoke-global-skill")
    resumed.step_result("install-yoke-global-skill", "done", detail={"again": True})
    resumed.fail(RuntimeError("stopped"))
    onboard_apply_late_steps.complete_report_path(
        resumed.path, action="project-write-board-art", detail={"commit": "abc"}
    )

    stored = json.loads(resumed.path.read_text())["steps"]
    assert stored[1:] == history
    assert stored[0]["status"] == "failed"
    assert stored[0]["step_id"] == "00-project-install-scaffold"


def test_ids_stay_unique_across_repeated_resumes() -> None:
    previous = _first_pass(
        ("project-checkout-register", "/code/a"),
        ("project-install-scaffold", ""),
        done=1,
    )
    second = json.loads(
        _resume(previous, ("project-checkout-register", "/code/b")).path.read_text()
    )
    second["steps"][0]["status"] = "done"

    third = _resume(second, ("project-checkout-register", "/code/c"))

    ids = [row["step_id"] for row in third.payload["steps"]]
    assert len(ids) == len(set(ids)), ids
    assert ids[0] == "00-project-checkout-register"
    assert {row["target"] for row in third.payload["steps"][1:]} == {"/code/a", "/code/b"}
