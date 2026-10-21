"""Which operations may run through a ``*-db-admin`` database door.

A ``*-db-admin`` connection runs each handler on this machine against a
universe's database over a tunnel, so every query is a network round trip:
ten to seventy-five times slower than the serving build beside its database.
When an https env serves the same universe, routine operations run there.
Only operations that need the database itself stay on the door, and this
module is the one place they are listed: diagnostic and repair functions by
id, and operator commands whose whole process (children included) needs the
door — schema convergence rehearsal, a deploy that replaces the API serving
its own run, creation bootstrap from a reviewed source checkout, and an
explicitly selected admin merge.

Client-side by construction: the answer comes from this machine's declared
connections, so a CLI-only install can apply it before dispatch.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Mapping, Optional

from yoke_contracts.api.function_call import FunctionError
from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.machine_config.schema import (
    DB_ADMIN_ENV_SUFFIX,
    same_universe_https_env,
)
from yoke_contracts.schema_authority import serving_build_authority_declared

USE_HTTPS_ENV = "use_https_env"

#: Registered functions that read or repair the database itself.
DIRECT_DATABASE_FUNCTIONS = frozenset(
    {
        "db.read.run",
        "doctor.run.run",
        "migration.content_identity.verify",
        "operator.data_repair.run",
    }
)

MIGRATION_REHEARSE_COMMAND = "migration rehearse"
SELF_DEPLOY_EXECUTE_COMMAND = "deployment-runs execute"
#: Creating a run from a reviewed source checkout through the explicit
#: launcher, when the serving API predates a merged creation fix.
CREATION_BOOTSTRAP_COMMAND = "deployment-runs create"

#: Source-dev self-maintenance: a merge whose operator explicitly selected
#: the door, for when the serving build cannot merge its own repair.
ADMIN_MERGE_COMMAND = "merge item"

#: Operator commands whose whole process runs through the database door.
DIRECT_DATABASE_COMMANDS = frozenset(
    {
        MIGRATION_REHEARSE_COMMAND,
        SELF_DEPLOY_EXECUTE_COMMAND,
        CREATION_BOOTSTRAP_COMMAND,
        ADMIN_MERGE_COMMAND,
    }
)

#: Inherited by child processes, so a declared command's subprocesses
#: (a deploy driver's stage runners) keep the door.
DECLARED_COMMAND_ENV = "YOKE_DIRECT_DATABASE_COMMAND"


def direct_database_environment(
    command: str, base: Optional[Mapping[str, str]] = None
) -> dict[str, str]:
    """*base* (default: this process) with *command* declared on the door."""
    if command not in DIRECT_DATABASE_COMMANDS:
        raise ValueError(f"{command!r} is not a declared direct-database command")
    return {**(os.environ if base is None else base), DECLARED_COMMAND_ENV: command}


@contextmanager
def direct_database_command(command: str) -> Iterator[None]:
    """Declare *command* on the door for this process and its children."""
    previous = os.environ.get(DECLARED_COMMAND_ENV)
    os.environ[DECLARED_COMMAND_ENV] = direct_database_environment(command)[
        DECLARED_COMMAND_ENV
    ]
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(DECLARED_COMMAND_ENV, None)
        else:
            os.environ[DECLARED_COMMAND_ENV] = previous


def paired_https_env() -> str:
    """The https env serving the universe the selected door administers.

    Empty unless the selected env is a ``*-db-admin`` door whose https
    sibling is configured, or when this process declared it serves the
    database it holds.
    """
    if serving_build_authority_declared():
        return ""
    try:
        env = str(machine_config_runtime.active_env() or "")
        if not env.endswith(DB_ADMIN_ENV_SUFFIX):
            return ""
        return same_universe_https_env(machine_config_runtime.load_config(), env)
    except Exception:  # noqa: BLE001 - no readable selection is no door
        return ""


def use_https_env_error(function_id: str) -> Optional[FunctionError]:
    """The ``use_https_env`` refusal for a routine call on the door, or None."""
    if function_id in DIRECT_DATABASE_FUNCTIONS:
        return None
    if os.environ.get(DECLARED_COMMAND_ENV, "") in DIRECT_DATABASE_COMMANDS:
        return None
    https_env = paired_https_env()
    if not https_env:
        return None
    door = f"{https_env}{DB_ADMIN_ENV_SUFFIX}"
    return FunctionError(
        code=USE_HTTPS_ENV,
        message=(
            f"{function_id} is a routine control-plane operation, and env "
            f"{door!r} is a direct database door that would run it on this "
            "machine with every query a round trip to the database. Env "
            f"{https_env!r} serves the same control plane beside its database."
        ),
        recovery_hint=(
            f"Rerun the same command with `--env {https_env}`. Keep `--env "
            f"{door}` for `yoke db read` diagnostics and the direct-database "
            "operations listed in yoke_contracts.direct_database_access."
        ),
    )


__all__ = [
    "ADMIN_MERGE_COMMAND",
    "CREATION_BOOTSTRAP_COMMAND",
    "DECLARED_COMMAND_ENV",
    "DIRECT_DATABASE_COMMANDS",
    "DIRECT_DATABASE_FUNCTIONS",
    "MIGRATION_REHEARSE_COMMAND",
    "SELF_DEPLOY_EXECUTE_COMMAND",
    "USE_HTTPS_ENV",
    "direct_database_command",
    "direct_database_environment",
    "paired_https_env",
    "use_https_env_error",
]
