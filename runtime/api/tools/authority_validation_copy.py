"""Provision and hydrate the validation database rehearsal applies to.

Governed migration rehearsal never touches a model's authoritative
database; it needs a separate database of the same shape, which this helper
derives beside the selected authority, creates when the cluster holds none,
fills with a credential-free copy of the authority, and binds for rehearsal
to read. It reports database names and the binding path, never a DSN, so
provisioning and rehearsing stay two commands with no credential in
between.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Sequence

import psycopg
from psycopg import sql

from yoke_core.domain import db_backend
from yoke_core.domain.migration_validation_binding import (
    DERIVED_DATABASE_SUFFIX,
    YOKE_VALIDATION_DSN_ENV,
    read_binding,
    write_binding,
)
from yoke_core.domain.scratch_database_authority import (
    refuse_scratch_database_on_administered_cluster,
)


#: The binding module owns both names: the fleet selector recognizes this
#: helper's output by them, so a second spelling here would let a rehearsal
#: database it provisioned be rehearsed as a tenant.
VALIDATION_DSN_ENV = YOKE_VALIDATION_DSN_ENV

#: Connected to only for the CREATE DATABASE that provisions a derived
#: target; the database being created cannot host its own creation.
MAINTENANCE_DB = "postgres"


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


def resolve_validation_dsn(authority_dsn: str) -> tuple[str, bool]:
    """Return the validation DSN to hydrate, and whether it was derived.

    A bound target wins so an operator can rehearse against a database of
    their own choosing; otherwise the target is the authority's own database
    name plus a suffix, on the same cluster and credentials, so nothing about
    the DSN has to be authored by hand.
    """

    bound = read_binding(VALIDATION_DSN_ENV)
    if bound:
        return bound, False
    parameters = psycopg.conninfo.conninfo_to_dict(authority_dsn)
    authority_db = str(parameters.get("dbname") or "").strip()
    if not authority_db:
        raise ValidationCopyError(
            "the selected authority names no database, so no validation "
            f"database can be derived from it; bind {VALIDATION_DSN_ENV} to "
            "a disposable database explicitly"
        )
    parameters["dbname"] = f"{authority_db}{DERIVED_DATABASE_SUFFIX}"
    return psycopg.conninfo.make_conninfo(**parameters), True


def create_database_if_absent(validation_dsn: str) -> None:
    """Create the database *validation_dsn* names when the cluster lacks it."""

    parameters = psycopg.conninfo.conninfo_to_dict(validation_dsn)
    dbname = str(parameters.get("dbname") or "")
    refuse_scratch_database_on_administered_cluster(
        dbname,
        target_dsn=validation_dsn,
    )
    parameters["dbname"] = MAINTENANCE_DB
    maintenance = psycopg.conninfo.make_conninfo(**parameters)
    try:
        with psycopg.connect(maintenance, autocommit=True) as conn:
            present = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
            ).fetchone()
            if present is None:
                conn.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname))
                )
    except psycopg.Error as exc:
        raise ValidationCopyError(
            f"could not create validation database {dbname!r} on the "
            f"authority's cluster: {type(exc).__name__}"
        ) from exc


def provision_validation_copy() -> tuple[str, str, Path]:
    """Bind, create when needed, and hydrate the validation database."""

    authority = db_backend.resolve_pg_dsn()
    validation_dsn, derived = resolve_validation_dsn(authority)
    if derived:
        create_database_if_absent(validation_dsn)
    authority_name, validation_name = _copy(authority, validation_dsn)
    binding = write_binding(VALIDATION_DSN_ENV, validation_dsn)
    return authority_name, validation_name, binding


def copy_authority_to_validation(validation_dsn: str) -> tuple[str, str]:
    """Replace a distinct validation DB with a dump of the active authority."""

    return _copy(db_backend.resolve_pg_dsn(), validation_dsn)


def _copy(authority: str, validation_dsn: str) -> tuple[str, str]:
    validation = str(validation_dsn or "").strip()
    if not validation:
        raise ValidationCopyError(f"{VALIDATION_DSN_ENV} must be set")
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
            "Provision the disposable database governed migration rehearsal "
            f"applies to. Uses the database bound as {VALIDATION_DSN_ENV} "
            "when one is bound, otherwise derives one beside the selected "
            "Postgres authority and creates it; then replaces its contents "
            "with a credential-redacted copy of that authority and writes "
            "the machine-local binding rehearsal reads."
        )
    )
    parser.parse_args(argv)
    try:
        authority_name, validation_name, binding = provision_validation_copy()
    except ValidationCopyError as exc:
        parser.error(str(exc))
    print(
        f"validation copy ready: authority={authority_name} "
        f"validation={validation_name} binding={binding}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
