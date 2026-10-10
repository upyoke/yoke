"""Native project fixture clocks at actual SQL writers and schema owners."""

from datetime import datetime
import importlib
import sqlite3

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant

NOW = parse_instant("2060-10-08T05:45:00.123456+05:45")
OPAQUE = "2060-10-08T00:00:00+09:00 unchanged"


@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Asia/Kathmandu"])
def test_project_item_and_flow_clock_writers_preserve_native_microseconds(
    test_db, zone
):
    from yoke_core.engines import _project_identity_test_helpers as fixtures
    from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

    test_db.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
    fixtures._seed_project(test_db, "yoke", name=OPAQUE)
    project = test_db.execute(
        "SELECT created_at,name FROM projects WHERE id=1"
    ).fetchone()
    assert isinstance(project[0], datetime) and project[0] == parse_instant(
        "2026-01-01T00:00:00Z"
    )
    assert project[1] == OPAQUE
    workflow, version = resolve_current_workflow_pin(test_db, "issue")
    fixtures._insert_item(
        test_db,
        17,
        title=OPAQUE,
        workflow_id=workflow,
        workflow_version_id=version,
        created_at=NOW,
        updated_at=NOW,
        merged_at=None,
    )
    item = test_db.execute(
        "SELECT created_at,updated_at,merged_at,title FROM items WHERE id=17"
    ).fetchone()
    assert item[:2] == (NOW, NOW) and all(isinstance(v, datetime) for v in item[:2])
    assert item[2:] == (None, OPAQUE)
    fixtures._insert_deployment_flow(
        test_db, "native-fixture", created_at=NOW, name=OPAQUE
    )
    flow = test_db.execute(
        "SELECT created_at,name FROM deployment_flows WHERE id='native-fixture'"
    ).fetchone()
    assert (
        isinstance(flow[0], datetime)
        and flow[0] == NOW
        and flow[0].microsecond == 123456
    )
    assert flow[1] == OPAQUE


@pytest.mark.parametrize(
    "value", ["", "2060-10-08", "2060-10-08T00:00:00", 17, datetime(2060, 10, 8)]
)
@pytest.mark.parametrize(
    "owner,field",
    [
        ("item", "created_at"),
        ("item", "updated_at"),
        ("item", "merged_at"),
        ("flow", "created_at"),
    ],
)
def test_provided_clock_refuses_before_schema_lookup_or_sql(value, owner, field):
    from yoke_core.engines import _project_identity_test_helpers as fixtures

    with pytest.raises(InvalidInstant):
        if owner == "item":
            fixtures._insert_item(object(), 17, **{field: value})
        else:
            fixtures._insert_deployment_flow(
                object(), "native-fixture", **{field: value}
            )


@pytest.mark.parametrize(
    "module",
    [
        "runtime.api.engines._doctor_hc_git_test_helpers",
        "runtime.api.engines.test_doctor_git",
        "runtime.api.engines.test_doctor_git_github",
    ],
)
def test_actual_git_doctor_schema_owners_declare_native_clocks(module):
    from yoke_core.domain.stored_instant_columns import STORED_INSTANT_COLUMNS

    conn = importlib.import_module(module)._make_conn()
    try:
        catalog = {
            (r[0], r[1]): r[2]
            for r in conn.execute(
                "SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='public'"
            ).fetchall()
        }
        present = set(STORED_INSTANT_COLUMNS) & set(catalog)
        assert len(present) >= 6
        assert all(catalog[key] == "timestamp with time zone" for key in present)
    finally:
        conn.close()


def test_explicit_sqlite_adapter_formats_only_finite_clock_fields():
    from yoke_core.engines import _project_identity_test_helpers as fixtures

    fields = fixtures._native_fields(
        "items", {"updated_at": NOW, "merged_at": None, "title": OPAQUE}
    )
    assert isinstance(fields["updated_at"], datetime)
    with sqlite3.connect(":memory:") as conn:
        assert fixtures._values(conn, "items", fields) == (
            "2060-10-08T00:00:00.123456Z",
            None,
            OPAQUE,
        )
