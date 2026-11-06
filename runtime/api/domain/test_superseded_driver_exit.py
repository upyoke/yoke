"""A driver whose run a newer release took over exits naming the successor.

Takeover settles the older run and records ``superseded_by_run_id``. The
older run's still-live driver then has its next bookkeeping write refused;
that refusal carries its own code and points at the successor to watch,
never at a re-drive of the cancelled run, and the driver exits successfully
without a traceback.
"""

from __future__ import annotations

from contextlib import nullcontext

from runtime.api.domain.deployment_execution_serving_authority_test_support import (
    _call,
)
from runtime.api.domain.deployment_run_execution_terminalized_refusal_test_support import (
    _create_and_cancel,
    _terminalize,
    serving_plane,
)
from yoke_core.domain import (
    deploy_pipeline_cli,
    deploy_pipeline_control_plane as control_plane,
    deploy_pipeline_run_updates as run_updates,
)
from yoke_core.domain.deployment_run_composition_guard import RUN_SUPERSEDED_CODE

__all__ = ["serving_plane"]  # re-exported fixture; silence unused-import lints

SUCCESSOR = "run-20261023-008"


def _cancelled_run(plane, *, successor: str = "") -> str:
    client, headers = plane["client"], plane["owner_headers"]
    session_id, conn = plane["owner_session"], plane["conn"]
    run_id = _create_and_cancel(client, headers, session_id)
    _terminalize(client, headers, session_id, conn, plane["owner_id"], run_id)
    if successor:
        conn.execute(
            "UPDATE deployment_runs SET superseded_by_run_id=%s WHERE id=%s",
            (successor, run_id),
        )
        conn.commit()
    return run_id


def _advance(plane, run_id: str, field: str, value: str) -> dict:
    response = _call(
        plane["client"],
        plane["owner_headers"],
        plane["owner_session"],
        "deployment_runs.execution.update",
        run_id=run_id,
        payload={"field": field, "value": value},
    )
    assert response.status_code == 400, response.text
    return response.json()["error"]


def test_a_superseded_run_refuses_with_its_successor(serving_plane) -> None:
    run_id = _cancelled_run(serving_plane, successor=SUCCESSOR)

    for field, value in (
        ("current_stage", "complete"),
        ("status", "succeeded"),
        ("status", "executing"),
    ):
        error = _advance(serving_plane, run_id, field, value)
        assert error["code"] == RUN_SUPERSEDED_CODE, (field, error)
        assert f"yoke deployment-runs get {SUCCESSOR}" in error["message"]
        assert f"instead of re-driving {run_id}" in error["message"]


def test_an_ordinary_cancelled_run_keeps_its_refusal(serving_plane) -> None:
    run_id = _cancelled_run(serving_plane)

    error = _advance(serving_plane, run_id, "current_stage", "complete")

    assert error["code"] == "update_failed"
    assert "a cancelled run cannot advance to a new stage" in error["message"]


def test_a_superseded_succeeded_run_keeps_its_settled_state(serving_plane) -> None:
    run_id = _cancelled_run(serving_plane, successor=SUCCESSOR)
    conn = serving_plane["conn"]
    conn.execute(
        "UPDATE deployment_runs SET status='succeeded', current_stage='complete' "
        "WHERE id=%s",
        (run_id,),
    )
    conn.commit()

    for field, value in (
        ("status", "failed"),
        ("current_stage", "item-qa-failed"),
        ("status", "executing"),
    ):
        error = _advance(serving_plane, run_id, field, value)
        assert error["code"] == RUN_SUPERSEDED_CODE, (field, error)
        assert SUCCESSOR in error["message"]
        row = conn.execute(
            "SELECT status, current_stage FROM deployment_runs WHERE id=%s",
            (run_id,),
        ).fetchone()
        assert tuple(row) == ("succeeded", "complete")


def _refusing(code: str):
    def write(run_id, field, value, **_kwargs):
        raise control_plane.DeploymentControlPlaneError(
            f"Error: {code}: refused {run_id}; watch {SUCCESSOR}", code=code
        )

    return write


def _drive(monkeypatch, capsys, code: str) -> tuple[int, str, str]:
    monkeypatch.setattr(control_plane, "update_run_field", _refusing(code))
    monkeypatch.setattr(
        deploy_pipeline_cli, "self_deploy_door", lambda _run: ("", nullcontext())
    )

    def runner(run_id, **_kwargs):
        run_updates.update_run_field(run_id, "current_stage", "complete")
        return 0

    exit_code = deploy_pipeline_cli.main(["run-20261023-007"], runner=runner)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_the_superseded_driver_exits_naming_the_successor(monkeypatch, capsys) -> None:
    exit_code, out, err = _drive(monkeypatch, capsys, RUN_SUPERSEDED_CODE)

    assert exit_code == 0
    assert "Deployment driver stopped after takeover:" in out
    assert f"watch {SUCCESSOR}" in out
    assert "re-drive" not in out
    assert "Traceback" not in out
    assert err == ""


def test_other_refusals_keep_their_re_drive_recovery(monkeypatch, capsys) -> None:
    exit_code, out, err = _drive(monkeypatch, capsys, "update_failed")

    assert exit_code == 1
    assert out == ""
    assert "repair the named cause, then re-drive run-20261023-007" in err
