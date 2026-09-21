"""Execution-context composition is derived once and then reused."""

from __future__ import annotations

from yoke_core.domain.deployment_run_pipe_format import pipe_row
from yoke_core.domain.deployment_runs_schema import RUN_FIELDS
from yoke_core.domain.handlers.deployment_run_execution import _enroll_carried_items


def test_a_recorded_composition_is_not_derived_again(monkeypatch) -> None:
    values = [""] * len(RUN_FIELDS)
    values[list(RUN_FIELDS).index("id")] = "run-once"
    values[list(RUN_FIELDS).index("carried_work")] = '{"schema":"carried_work.v1"}'
    monkeypatch.setattr(
        "yoke_core.domain.deployment_runs_crud_query.cmd_get",
        lambda _run_id: pipe_row(values),
    )
    called: list[str] = []

    def _boom(*_args, **_kwargs):
        called.append("enroll")
        return ()

    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_carried_membership.enroll_carried_members",
        _boom,
    )
    assert _enroll_carried_items("run-once") == []
    assert called == []
