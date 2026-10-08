"""Read-only, secret-free catalog and format census of classified DB instants.

Every database read uses the registered CLI. This tool never connects to a
database, applies history, repairs a value, or logs credentials or row content.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from yoke_core.domain.stored_instant_columns import STORED_INSTANT_COLUMNS


_QUALIFIED = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(\.[0-9]{1,6})?([Zz]|[+-][0-9]{2}:[0-9]{2})$"
)


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _read(environment: str, query: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["yoke", "--env", environment, "db", "read", query],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            "instant_census_read_refused: registered db.read did not complete; "
            "retain this partial census and resolve the named connection/read "
            f"refusal before migration. {completed.stderr or completed.stdout}"
        )
    result = json.loads(completed.stdout)
    if result.get("truncated"):
        raise RuntimeError("instant_census_truncated: narrow the registered read.")
    return result


def catalog_query() -> str:
    return (
        "SELECT COALESCE(jsonb_agg(jsonb_build_object("
        "'table',table_name,'column',column_name,'type',data_type,"
        "'nullable',is_nullable) ORDER BY table_name,ordinal_position),'[]') "
        "AS catalog FROM information_schema.columns WHERE table_schema = 'public'"
    )


def table_query(table: str, columns: list[dict[str, Any]]) -> str:
    projections = ["COUNT(*) AS row_count"]
    for index, column in enumerate(columns):
        name = _identifier(column["column"])
        projections.append(f"COUNT(*) FILTER (WHERE {name} IS NULL) AS n{index}")
        if column["type"] != "text":
            continue
        projections.extend(
            [
                f"COUNT(*) FILTER (WHERE {name} = '') AS b{index}",
                f"COUNT(*) FILTER (WHERE {name} <> '' AND {name} !~ '{_QUALIFIED}') AS q{index}",
                f"COUNT(*) FILTER (WHERE {name} <> '' AND NOT "
                f"pg_input_is_valid({name},'timestamp with time zone')) AS m{index}",
                f"COUNT(*) FILTER (WHERE {name} ~ '-00:00$') AS u{index}",
            ]
        )
    return f"SELECT {', '.join(projections)} FROM {_identifier(table)}"


def census(environment: str, output: Path) -> int:
    report: dict[str, Any] = {
        "environment": environment,
        "complete": False,
        "columns": [],
        "missing": [],
        "unclassified": [],
    }
    try:
        catalog = _read(environment, catalog_query())["rows"][0][0]
        if isinstance(catalog, str):
            catalog = json.loads(catalog)
        by_key = {(column["table"], column["column"]): column for column in catalog}
        by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
        classified = set(STORED_INSTANT_COLUMNS)
        for table, name in STORED_INSTANT_COLUMNS:
            column = by_key.get((table, name))
            if column is None:
                report["missing"].append({"table": table, "column": name})
            else:
                by_table[table].append(column)
        for column in catalog:
            name = column["column"]
            if (column["table"], name) not in classified and (
                name.endswith("_at")
                or name
                in {
                    "timestamp",
                    "last_heartbeat",
                    "last_updated",
                    "keepalive_until",
                    "connected_until",
                    "github_body_compact_pending",
                }
            ):
                report["unclassified"].append(column)
        for table, columns in sorted(by_table.items()):
            result = _read(environment, table_query(table, columns))
            values = dict(zip(result["columns"], result["rows"][0]))
            for index, column in enumerate(columns):
                report["columns"].append(
                    {
                        **column,
                        "rows": values["row_count"],
                        "null": values[f"n{index}"],
                        "blank": values.get(f"b{index}", 0),
                        "non_rfc3339": values.get(f"q{index}", 0),
                        "invalid_calendar_or_value": values.get(f"m{index}", 0),
                        "unknown_offset": values.get(f"u{index}", 0),
                    }
                )
            output.write_text(json.dumps(report, indent=2) + "\n")
            print(
                f"instant-census table={table} columns={len(columns)} "
                f"rows={values['row_count']}",
                flush=True,
            )
        report["complete"] = True
        return 0
    except (RuntimeError, ValueError, KeyError, IndexError) as exc:
        report["refusal"] = str(exc)
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        output.write_text(json.dumps(report, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return census(args.environment, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
