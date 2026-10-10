# ruff: noqa: F811
"""A run occupies the server origins it deploys to until its QA settles.

Exercised through the real start transition (``status -> executing``) on the
shared deployment-runs fixture, with a second project whose environment
record names the same host under a different spelling.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_runs as dr
from yoke_core.domain import deploy_target_occupancy as occupancy
from yoke_core.domain import deployment_qa_stage_outstanding as outstanding
from runtime.api.deployment_runs_test_db import db_path  # noqa: F401 — fixture
from runtime.api.fixtures.file_test_db import connect_test_db

STAGE_URL = "https://app.stage.example.test"
QA_STAGES = (
    '[{"name":"deploy"},'
    '{"name":"item-qa","stage_kind":"qa","step_runner":"qa","scope":"item"},'
    '{"name":"complete"}]'
)


def _seed(db_path: str) -> None:
    conn = connect_test_db(db_path)
    conn.execute("UPDATE environments SET url=%s WHERE id=202", (STAGE_URL,))
    conn.execute("UPDATE environments SET url='https://app.example.test' WHERE id=201")
    conn.execute("INSERT INTO sites (id, project_id, name) VALUES (102, 2, 'webapp')")
    # A different record, in a different project, for the same server.
    conn.execute(
        "INSERT INTO environments (id, site, project_id, name, url) "
        "VALUES (203, 102, 2, 'stage', %s)",
        ("HTTPS://App.Stage.Example.Test/",),
    )
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, target_tier, target_environment_id) "
        "VALUES ('web-stage', 2, 'Web stage', %s, 'persistent', 203)",
        (QA_STAGES,),
    )
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, target_tier, target_environment_id) "
        "VALUES ('yoke-stage', 1, 'Yoke stage', "
        '\'[{"name":"deploy"},{"name":"complete"}]\', \'persistent\', 202)'
    )
    conn.commit()
    conn.close()


def _start(db_path: str, run_id: str):
    return dr.cmd_update(run_id, "status", "executing", db_path=db_path)


def _qa_open(monkeypatch: pytest.MonkeyPatch, lines: tuple[str, ...]) -> None:
    monkeypatch.setattr(
        outstanding,
        "qa_stage_outstanding",
        lambda conn, *, run_id, stage_name: outstanding.QaStageOutstanding(
            lines=lines, subjects=1, waiting=1 if lines else 0
        ),
    )


def test_environment_records_naming_one_host_share_an_origin(db_path: str) -> None:
    _seed(db_path)
    web = dr.cmd_create_run("externalwebapp", "web-stage", db_path=db_path)
    yoke = dr.cmd_create_run("yoke", "yoke-stage", db_path=db_path)
    conn = connect_test_db(db_path)
    try:
        assert occupancy.run_target(conn, web).origins == (STAGE_URL,)
        assert occupancy.run_target(conn, yoke).origins == (STAGE_URL,)
    finally:
        conn.close()


def test_second_run_on_an_occupied_origin_refuses_naming_the_holder(
    db_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(db_path)
    _qa_open(monkeypatch, ("member WEB-1: verdict not recorded",))
    holder = dr.cmd_create_run("externalwebapp", "web-stage", db_path=db_path)
    assert _start(db_path, holder) is None
    second = dr.cmd_create_run("yoke", "yoke-stage", db_path=db_path)

    refusal = _start(db_path, second)

    assert refusal is not None and "target_occupied" in refusal
    assert holder in refusal and STAGE_URL in refusal
    assert "member WEB-1: verdict not recorded" in refusal
    assert f"yoke deployment-runs terminalize {holder}" in refusal
    assert dr.cmd_get(second, field="status", db_path=db_path) == "created"


def test_occupancy_releases_once_qa_settles(
    db_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(db_path)
    _qa_open(monkeypatch, ("member WEB-1: verdict not recorded",))
    holder = dr.cmd_create_run("externalwebapp", "web-stage", db_path=db_path)
    assert _start(db_path, holder) is None
    second = dr.cmd_create_run("yoke", "yoke-stage", db_path=db_path)
    assert _start(db_path, second) is not None

    _qa_open(monkeypatch, ())

    assert _start(db_path, second) is None


def test_a_run_without_qa_holds_until_terminal(db_path: str) -> None:
    _seed(db_path)
    holder = dr.cmd_create_run("yoke", "yoke-stage", db_path=db_path)
    assert _start(db_path, holder) is None
    second = dr.cmd_create_run("externalwebapp", "web-stage", db_path=db_path)
    refusal = _start(db_path, second)
    assert refusal is not None and "held until the run is terminal" in refusal

    conn = connect_test_db(db_path)
    conn.execute("UPDATE deployment_runs SET status='cancelled' WHERE id=%s", (holder,))
    conn.commit()
    conn.close()

    assert _start(db_path, second) is None


def test_a_different_origin_is_not_occupied(db_path: str) -> None:
    _seed(db_path)
    holder = dr.cmd_create_run("yoke", "yoke-stage", db_path=db_path)
    assert _start(db_path, holder) is None
    production = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)

    assert _start(db_path, production) is None


def test_production_origins_are_occupied_too(db_path: str) -> None:
    _seed(db_path)
    first = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    assert _start(db_path, first) is None
    second = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)

    refusal = _start(db_path, second)

    assert refusal is not None and "https://app.example.test" in refusal
