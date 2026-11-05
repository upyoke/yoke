"""One registry-wide proof owns storage equivalence across session zones."""

from collections import defaultdict
from datetime import timedelta
from pathlib import Path
import ast

from runtime.api.fixtures.session_zones import SESSION_ZONES
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.stored_instant_columns import STORED_INSTANT_COLUMNS


def test_registered_storage_is_independent_of_session_zone(test_db):
    catalog = {
        (row[0], row[1]): row[2]
        for row in test_db.execute(
            "SELECT table_name, column_name, data_type "
            "FROM information_schema.columns WHERE table_schema='public'"
        ).fetchall()
    }
    by_table = defaultdict(list)
    for table, column in STORED_INSTANT_COLUMNS:
        assert catalog.get((table, column)) == "timestamp with time zone", (
            table,
            column,
        )
        by_table[table].append(column)

    # Clone only declared clock columns, without unrelated business constraints.
    for index, (table, columns) in enumerate(sorted(by_table.items())):
        names = ", ".join(f'"{column}"' for column in columns)
        test_db.execute(
            f"CREATE TEMP TABLE instant_probe_{index} AS "
            f'SELECT {names} FROM "{table}" WITH NO DATA'
        )

    moments = [
        parse_instant("1969-12-31T23:59:59.123456Z"),
        parse_instant("2026-10-09T00:00:00.000001Z"),
        None,
    ]
    for write_zone in SESSION_ZONES:
        test_db.execute("SELECT set_config('TimeZone', %s, true)", (write_zone,))
        for index, columns in enumerate(by_table[table] for table in sorted(by_table)):
            test_db.execute(f"TRUNCATE instant_probe_{index}")
            placeholders = ", ".join(["%s"] * len(columns))
            for moment in moments:
                test_db.execute(
                    f"INSERT INTO instant_probe_{index} VALUES ({placeholders})",
                    (moment,) * len(columns),
                )
        for read_zone in SESSION_ZONES:
            test_db.execute("SELECT set_config('TimeZone', %s, true)", (read_zone,))
            for index, table in enumerate(sorted(by_table)):
                first = by_table[table][0]
                rows = test_db.execute(
                    f'SELECT * FROM instant_probe_{index} ORDER BY "{first}" NULLS LAST'
                ).fetchall()
                assert len(rows) == len(moments)
                for row, moment in zip(rows, moments):
                    assert all(value == moment for value in row), table
                    assert all(
                        value is None or format_instant(value) == format_instant(moment)
                        for value in row
                    ), table
                    if moment is not None:
                        assert row[0].utcoffset() != timedelta(0)


def test_session_zone_parametrizations_share_the_declared_odd_offsets():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    offsets = [
        datetime(2026, 10, 9, tzinfo=ZoneInfo(zone)).utcoffset()
        for zone in SESSION_ZONES
    ]
    assert offsets[0] < timedelta(0) < offsets[1]
    assert all(offset.total_seconds() % 3600 != 0 for offset in offsets)
    root = Path(__file__).resolve().parents[3]
    for path in (root / "runtime/api").rglob("test_*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "parametrize"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "zone"
            ):
                continue
            assert ast.unparse(node.args[1]) in {
                "SESSION_ZONES",
                "SESSION_ZONES[1:]",
            }, f"{path.relative_to(root)}:{node.lineno}: use SESSION_ZONES"
