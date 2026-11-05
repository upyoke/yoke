"""Doctor diagnostic text formats native SQL results as canonical UTC."""

import pytest

from runtime.api.fixtures.session_zones import SESSION_ZONES
from yoke_core.engines import doctor_hc_db as runs
from yoke_core.engines import doctor_hc_db_events_ledger as ledger
from yoke_core.engines import doctor_hc_db_project_schema as schema
from yoke_core.engines import doctor_hc_qa_runs as qa
from yoke_core.engines import doctor_hc_stop_hook_chain as stop
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_contracts.timestamps import parse_instant

WIRE = "2026-10-05T00:00:00.123456Z"


@pytest.mark.parametrize("zone", SESSION_ZONES[1:])
@pytest.mark.parametrize(
    "module,check,rows",
    [
        (
            runs,
            runs.hc_orphaned_runs,
            [[dict(id="run", project="project", status="created", created_at=None)]],
        ),
        (
            runs,
            runs.hc_stale_runs,
            [
                [
                    dict(
                        id="run",
                        project="project",
                        current_stage="check",
                        started_at=None,
                    )
                ]
            ],
        ),
        (
            qa,
            qa.hc_qa_runs_mutated,
            [
                [
                    dict(
                        id=1,
                        qa_requirement_id=2,
                        raw_result="resolved by",
                        created_at=None,
                    )
                ]
            ],
        ),
        (
            schema,
            schema.hc_migration_audit,
            [
                [
                    dict(
                        id=1,
                        migration_name="migration",
                        state="failed_live_apply",
                        failure_reason="failure",
                        started_at=None,
                    )
                ],
                [],
            ],
        ),
        (
            ledger,
            ledger.hc_events_destructive_maintenance_audit,
            [
                [dict(id=1, created_at=None, cmd="command")],
                [dict(id=2, migration_name="events-prune", started_at=None)],
            ],
        ),
        (
            stop,
            stop.hc_stop_hook_chain_end_deferred,
            [[dict(session_id="session", item_id=1, created_at=None)]],
        ),
    ],
)
def test_diagnostic_clocks_from_non_utc_sql_results(
    test_db, monkeypatch, zone, module, check, rows
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    native = test_db.execute(
        "SELECT %s::timestamptz", (parse_instant(WIRE),)
    ).fetchone()[0]
    batches = iter(
        [
            [
                {
                    key: native if key.endswith("_at") else value
                    for key, value in row.items()
                }
                for row in batch
            ]
            for batch in rows
        ]
    )
    monkeypatch.setattr(module, "query_rows", lambda *a, **k: next(batches))
    monkeypatch.setattr(
        module._base if hasattr(module, "_base") else schema,
        "_table_exists" if hasattr(module, "_base") else "_schema_table_exists",
        lambda *a: True,
    )
    if module is schema:
        monkeypatch.setattr(schema, "_schema_table_exists", lambda *a: True)
    if module is stop:
        monkeypatch.setattr(stop, "_column_exists", lambda *a: True)
    rec = RecordCollector()
    check(test_db, DoctorArgs(), rec)
    detail = "\n".join(row.detail for row in rec.results)
    assert WIRE in detail
    assert str(native) not in detail
