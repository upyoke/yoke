"""Catalog CAS and delivery succession retain exact native instant ordering."""

from datetime import datetime, timedelta

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import qa_plan_edit, qa_plan_management
from yoke_core.domain.deployment_flow_succession import successor_flows
from yoke_core.domain.deployment_run_composition_guard import has_frozen_composition
from yoke_core.domain.qa_plan_detail import get_plan


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_editor_tokens_compare_instants_and_keep_microsecond_cas(
    test_db, monkeypatch, zone
):
    from runtime.api.qa_plan_edit_test_support import _edit, _plan, _updated_at
    from yoke_core.domain.qa_catalog_reads import get_method

    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    before = parse_instant("1969-12-31T23:59:59.999999Z")
    after = before + timedelta(microseconds=1)
    monkeypatch.setattr(qa_plan_management, "_next_updated_at", lambda: before)
    monkeypatch.setattr(qa_plan_edit, "_next_updated_at", lambda: after)
    plan = _plan(test_db)
    detail = get_plan(test_db, plan_id=plan["id"])
    assert detail["created_at"] == detail["updated_at"] == format_instant(before)
    assert detail["retired_at"] is None
    method = get_method(test_db, method_id="command", project="yoke")
    related = next(row for row in method["plans"] if row["id"] == plan["id"])
    assert related["outcome_summary"]["last_at"] is None
    equivalent = "1969-12-31T18:59:59.999999-05:00"
    unchanged = _edit(test_db, plan, base_updated_at=equivalent)
    assert unchanged["unchanged"] and unchanged["updated_at"] == detail["updated_at"]
    changed = _edit(test_db, plan, base_updated_at=equivalent, description="New proof")
    assert not changed["unchanged"]
    assert (
        changed["updated_at"]
        == _updated_at(test_db, plan["id"])
        == format_instant(after)
    )
    with pytest.raises(qa_plan_edit.QaPlanConflictError, match="changed after"):
        _edit(test_db, plan, base_updated_at=equivalent, description="New proof")
    clock = test_db.execute(
        "SELECT updated_at FROM qa_plans WHERE id=%s", (plan["id"],)
    ).fetchone()[0]
    assert isinstance(clock, datetime) and clock == after


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_successors_order_native_clocks_then_identity(test_db, zone):
    from runtime.api.domain.test_deployment_flow_succession import _flow

    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    _flow(test_db, "clock-root", status="disabled")
    for flow_id, created_at in [
        ("clock-zz-old", "1969-12-31T23:59:59.999998Z"),
        ("clock-aa-new", "1969-12-31T18:59:59.999999-05:00"),
        ("clock-bb-new", "1970-01-01T05:29:59.999999+05:30"),
    ]:
        _flow(test_db, flow_id, supersedes="clock-root", created_at=created_at)
    assert successor_flows(test_db, ["clock-root"])["clock-root"] == "clock-bb-new"
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,created_at) "
        "VALUES('clock-freeze',1,'clock-bb-new','main','created',%s)",
        (parse_instant("1969-12-31T23:59:59.999999Z"),),
    )
    assert not has_frozen_composition(test_db, "clock-freeze")
    test_db.execute(
        "UPDATE deployment_runs SET composition_frozen_at=%s WHERE id='clock-freeze'",
        (parse_instant("1969-12-31T23:59:59.999999Z"),),
    )
    assert has_frozen_composition(test_db, "clock-freeze")


@pytest.mark.parametrize(
    "bad",
    ["1969-12-31", "1969-12-31T23:59:59", "1970-01-01T00:00:00.0000001Z", "garbage"],
)
def test_editor_refuses_invalid_clock_before_database_access(bad):
    with pytest.raises(InvalidInstant, match="invalid_instant"):
        qa_plan_edit.edit_plan(
            object(),
            project="yoke",
            slug="clock-plan",
            base_updated_at=bad,
            name="Clock plan",
            description="",
            success_policy_id="all-pass",
            success_policy_params={},
            cases=[],
        )


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_builtin_method_seeding_keeps_native_updates_and_original_creation(
    test_db, monkeypatch, zone
):
    from yoke_core.domain import qa_catalog_schema

    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    original = test_db.execute(
        "SELECT created_at FROM qa_methods WHERE id='command'"
    ).fetchone()[0]
    assert isinstance(original, datetime)
    stamp = parse_instant("1969-12-31T23:59:59.999999Z")
    monkeypatch.setattr(qa_catalog_schema, "utc_now", lambda: stamp)
    qa_catalog_schema.seed_builtin_qa_methods(test_db)
    before = test_db.execute(
        "SELECT created_at,updated_at FROM qa_methods WHERE id='command'"
    ).fetchone()
    assert tuple(before) == (original, stamp)
    stamp += timedelta(microseconds=1)
    qa_catalog_schema.seed_builtin_qa_methods(test_db)
    after = test_db.execute(
        "SELECT created_at,updated_at FROM qa_methods WHERE id='command'"
    ).fetchone()
    assert tuple(after) == (original, stamp)
