"""The validation-only database binding governed migration rehearsal reads.

Rehearsal never applies a module to a model's authoritative database: it
applies each one to a separate, disposable database of the same shape. That
database is named by ``<connection_env_var>_VALIDATION`` -- an environment
variable when a caller exports one, otherwise a machine-local file this
module owns.

The file exists so that provisioning the validation database and rehearsing
against it can be two separate commands without the DSN passing through the
operator's hands in between: the provisioner writes the binding, rehearsal
reads it, and neither ever prints it.

Rehearsal also leaves that database in place, which makes this module the
one surface that can tell a rehearsal target apart from a database something
serves. Anything enumerating a cluster reads :func:`recorded_bindings` for
that answer rather than guessing from a name alone.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from yoke_contracts.control_plane_locality import PG_DSN_ENV

#: Appended to a model's declared ``runner.config.connection_env_var``.
VALIDATION_ENV_SUFFIX = "_VALIDATION"

#: Extension of the machine-local binding file under ``~/.yoke/secrets``.
BINDING_FILE_SUFFIX = "dsn"

#: Appended to the authority's own database name when provisioning derives a
#: rehearsal target instead of being pointed at one. A database carrying it
#: is a rehearsal surface by construction, whatever cluster it sits on.
DERIVED_DATABASE_SUFFIX = "_validation"


@dataclass(frozen=True)
class RecordedBinding:
    """One validation binding this machine can see, named without its DSN."""

    env_var: str
    source: str
    database: str


def validation_env_var(connection_env_var: str) -> str:
    """Return the validation binding name for a model's authority binding."""
    return f"{connection_env_var}{VALIDATION_ENV_SUFFIX}"


#: The validation binding for the Yoke control plane's own Postgres authority.
YOKE_VALIDATION_DSN_ENV = validation_env_var(PG_DSN_ENV)


def binding_file(env_var: str) -> Path:
    """Return the machine-local file that may carry *env_var*'s DSN."""
    from yoke_cli.config.secrets import secret_path_no_create

    return secret_path_no_create(env_var, BINDING_FILE_SUFFIX)


def binding_directory() -> Path:
    """Return the machine-local directory binding files are written to."""
    return binding_file(YOKE_VALIDATION_DSN_ENV).parent


def read_binding(env_var: str) -> str:
    """Return the DSN bound to *env_var*, or an empty string when unbound.

    The environment wins so a caller can point one run somewhere else
    without disturbing the machine-local binding.
    """
    exported = os.environ.get(env_var, "").strip()
    if exported:
        return exported
    try:
        return binding_file(env_var).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def recorded_bindings() -> Tuple[RecordedBinding, ...]:
    """Return every validation binding on this machine, DSNs never included.

    Both channels count, and both are returned even when they disagree:
    :func:`read_binding` lets an export win for the run it is steering, but
    the database the machine-local file names is still a rehearsal surface
    sitting on its cluster, and a caller excluding rehearsal surfaces has to
    know about both.

    ``database`` is empty when a binding carries no readable database name.
    Callers report that rather than dropping the entry, because an
    unreadable binding hides exactly the database that must not be mistaken
    for something a release has to keep serving.
    """
    found = [
        RecordedBinding(env_var, "environment", _dsn_database(value))
        for env_var, value in sorted(os.environ.items())
        if env_var.endswith(VALIDATION_ENV_SUFFIX) and value.strip()
    ]
    pattern = f"*{VALIDATION_ENV_SUFFIX}.{BINDING_FILE_SUFFIX}"
    try:
        files = sorted(binding_directory().glob(pattern))
    except OSError:
        files = []
    for path in files:
        try:
            dsn = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if dsn:
            found.append(RecordedBinding(path.stem, str(path), _dsn_database(dsn)))
    return tuple(found)


def write_binding(env_var: str, dsn: str) -> Path:
    """Persist *dsn* as *env_var*'s owner-only machine-local binding."""
    from yoke_cli.config.secrets import replace_secret_file

    return replace_secret_file(binding_file(env_var), env_var, dsn)


def _dsn_database(dsn: str) -> str:
    """Return the database a binding DSN opens, or ``""`` when unreadable."""
    import psycopg
    from psycopg import conninfo

    try:
        parsed = conninfo.conninfo_to_dict(dsn)
    except psycopg.Error:
        return ""
    return str(parsed.get("dbname") or "").strip()


__all__ = [
    "BINDING_FILE_SUFFIX",
    "DERIVED_DATABASE_SUFFIX",
    "RecordedBinding",
    "VALIDATION_ENV_SUFFIX",
    "YOKE_VALIDATION_DSN_ENV",
    "binding_directory",
    "binding_file",
    "read_binding",
    "recorded_bindings",
    "validation_env_var",
    "write_binding",
]
