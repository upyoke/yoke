"""Hydrate an explicit validation database from the selected Postgres authority."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Sequence

import psycopg

from yoke_core.domain import db_backend


VALIDATION_DSN_ENV = "YOKE_PG_DSN_VALIDATION"


class ValidationCopyError(RuntimeError):
    """The authority-to-validation copy could not be completed safely."""


def _database_identity(dsn: str) -> tuple[str, str, str]:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT current_database(), "
            "COALESCE(inet_server_addr()::text, 'local-socket'), "
            "inet_server_port()::text"
        ).fetchone()
    if row is None:
        raise ValidationCopyError("database identity query returned no row")
    return str(row[0]), str(row[1]), str(row[2])


def _subprocess_connection(dsn: str) -> tuple[str, dict[str, str]]:
    """Return password-free conninfo plus a libpq subprocess environment."""

    parameters = psycopg.conninfo.conninfo_to_dict(dsn)
    password = parameters.pop("password", None)
    child_env = dict(os.environ)
    if password:
        child_env["PGPASSWORD"] = password
    else:
        child_env.pop("PGPASSWORD", None)
    return psycopg.conninfo.make_conninfo(**parameters), child_env


def _reset_validation_schema(dsn: str) -> None:
    """Clear the disposable validation schema without archive drop ordering."""

    with psycopg.connect(dsn) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")


def copy_authority_to_validation(validation_dsn: str) -> tuple[str, str]:
    """Replace a distinct validation DB with a dump of the active authority."""

    validation = str(validation_dsn or "").strip()
    if not validation:
        raise ValidationCopyError(f"{VALIDATION_DSN_ENV} must be set")
    authority = db_backend.resolve_pg_dsn()
    authority_identity = _database_identity(authority)
    validation_identity = _database_identity(validation)
    if authority_identity == validation_identity:
        raise ValidationCopyError(
            "validation database resolves to the authoritative database"
        )
    authority_arg, authority_env = _subprocess_connection(authority)
    validation_arg, validation_env = _subprocess_connection(validation)

    with tempfile.TemporaryDirectory(prefix="yoke-validation-copy-") as raw_tmp:
        archive = Path(raw_tmp) / "authority.dump"
        dumped = subprocess.run(
            [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(archive),
                authority_arg,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=authority_env,
        )
        if (
            dumped.returncode != 0
            or not archive.is_file()
            or archive.stat().st_size == 0
        ):
            raise ValidationCopyError(
                "authority dump failed: " + (dumped.stderr or "unknown error")[-800:]
            )
        _reset_validation_schema(validation)
        restored = subprocess.run(
            [
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                validation_arg,
                str(archive),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=validation_env,
        )
        if restored.returncode != 0:
            raise ValidationCopyError(
                "validation restore failed: "
                + (restored.stderr or "unknown error")[-800:]
            )
    return authority_identity[0], validation_identity[0]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replace the database named by YOKE_PG_DSN_VALIDATION with a "
            "credential-redacted copy of the selected Postgres authority."
        )
    )
    parser.parse_args(argv)
    try:
        authority_name, validation_name = copy_authority_to_validation(
            os.environ.get(VALIDATION_DSN_ENV, "")
        )
    except ValidationCopyError as exc:
        parser.error(str(exc))
    print(
        f"validation copy ready: authority={authority_name} "
        f"validation={validation_name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
