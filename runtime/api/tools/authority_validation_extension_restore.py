"""Stage source extension versions on a DSN-shaped validation copy."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Sequence

import psycopg
from psycopg import sql


class ExtensionRestoreError(RuntimeError):
    """The copy could not pin source extensions before restore."""


def write_restore_list_omitting_schemas(
    dump: Path, schemas: Sequence[str], list_path: Path
) -> None:
    """Comment CREATE SCHEMA entries the copy already staged."""

    from yoke_core.domain.migration_fleet_preflight_transfer import (
        _listed_schema,
    )

    listing = subprocess.run(
        ["pg_restore", "-l", str(dump)],
        capture_output=True,
        text=True,
        check=False,
    )
    if listing.returncode != 0:
        raise ExtensionRestoreError(
            "pg_restore -l failed: " + (listing.stderr or "unknown error")[-800:]
        )
    wanted = set(schemas)
    omitted: set[str] = set()
    lines: list[str] = []
    for line in (listing.stdout or "").splitlines(keepends=True):
        listed = _listed_schema(line)
        if listed is not None and listed in wanted:
            omitted.add(listed)
            lines.append(";" + line)
        else:
            lines.append(line)
    unmatched = sorted(wanted - omitted)
    if unmatched:
        raise ExtensionRestoreError(
            "dump has no CREATE SCHEMA for " + ", ".join(unmatched)
        )
    list_path.write_text("".join(lines), encoding="utf-8")


def prepare_extension_restore(
    authority: str, validation: str, dump: Path, list_path: Path
) -> Path | None:
    """Install the source's extension versions before restore.

    A schema reset drops those extensions. The dump then installs the
    cluster default, and views over ``current_database_statements_read()``
    fail when that default widens the rowtype. Fleet preflight stages the
    pin the same way; this is the DSN-shaped copy of that step.
    """

    from yoke_core.domain.migration_fleet_preflight_extensions import (
        PREEXISTING_SCHEMAS,
    )

    with psycopg.connect(authority) as conn:
        pins = [
            (str(row[0]), str(row[1]), str(row[2]))
            for row in conn.execute(
                "SELECT e.extname, e.extversion, n.nspname "
                "FROM pg_extension e "
                "JOIN pg_namespace n ON n.oid = e.extnamespace "
                "ORDER BY e.extname"
            ).fetchall()
        ]
    if not pins:
        return None
    schemas = tuple(
        dict.fromkeys(
            schema
            for _name, _version, schema in pins
            if schema not in PREEXISTING_SCHEMAS
        )
    )
    with psycopg.connect(validation, autocommit=True) as conn:
        for schema in schemas:
            conn.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                    sql.Identifier(schema)
                )
            )
        for name, version, schema in pins:
            conn.execute(
                sql.SQL(
                    "CREATE EXTENSION IF NOT EXISTS {} "
                    "WITH SCHEMA {} VERSION {}"
                ).format(
                    sql.Identifier(name),
                    sql.Identifier(schema),
                    sql.Literal(version),
                )
            )
    if not schemas:
        return None
    write_restore_list_omitting_schemas(dump, schemas, list_path)
    return list_path
