"""Rehearsal plan for a model that converges through its project's own boot.

A ``named_databases`` fleet is converged by the command its model declares,
run from the project checkout exactly as that project's server runs it at
boot. The engine does not import the project's code: it binds the throwaway
copy's DSN to the model's ``connection_env_var`` and runs the declared
command, so the boot sequence being rehearsed is the project's own, not an
engine approximation of it. The membership ledger the model declares answers
what was pending before and what applied after.

The command runs with a minimal explicit environment rather than the
operator's, and only a project admin can write the ``migration_fleet``
capability that names it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from yoke_core.domain.migration_fleet_preflight import RehearsalPlan

#: One boot converge of one copy. A command that outlives it is a failed
#: verdict that names this limit rather than a rehearsal that never ends.
COMMAND_TIMEOUT_SECONDS = 1800

_OUTPUT_TAIL_CHARS = 2000

#: Environment a declared command inherits: a shell's locale, home and temp
#: directories, certificate paths, and the project's own uv configuration.
_PASSTHROUGH_ENV = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TMPDIR",
        "USER",
        "XDG_CACHE_HOME",
    }
)
_PASSTHROUGH_PREFIXES = ("UV_",)


class DeclaredCommandError(RuntimeError):
    """A declared boot or verify command did not succeed on the copy."""


def declared_plan(
    model: Mapping[str, Any], fleet: Mapping[str, Any], checkout: Path
) -> RehearsalPlan:
    """Bind the generic kernel to a model's declared ledger and commands."""
    from yoke_core.domain import migration_ledger_contract
    from yoke_core.domain.migration_history import ordered_entries

    config = model["runner"]["config"]
    ledger = migration_ledger_contract.parse(config["ledger"])
    root = checkout.expanduser().resolve()
    history = tuple(
        entry.name for entry in ordered_entries(root / config["modules_dir"])
    )
    env_var = str(config["connection_env_var"])

    def pending_names(conn: Any, names: Sequence[str]) -> Tuple[str, ...]:
        present = conn.execute("SELECT to_regclass(%s)", (ledger.table,)).fetchone()[0]
        if present is None:
            return tuple(names)
        from yoke_core.domain.migration_boot_ledger import applied_names

        applied = applied_names(conn, ledger)
        return tuple(name for name in names if name not in applied)

    def converge(conn: Any, copy_dsn: str) -> None:
        # End this session's read snapshot first: the boot command alters the
        # very tables the pending read touched, and would wait on it forever.
        conn.rollback()
        run_declared(fleet["converge_argv"], cwd=root, env_var=env_var, dsn=copy_dsn)

    verify_argv = fleet.get("verify_argv")

    def verify(conn: Any, copy_dsn: str) -> Optional[str]:
        conn.rollback()
        try:
            run_declared(verify_argv, cwd=root, env_var=env_var, dsn=copy_dsn)
        except DeclaredCommandError as exc:
            return str(exc)
        return None

    return RehearsalPlan(
        history=history,
        pending_names=pending_names,
        converge=converge,
        post_converge_validator=verify if verify_argv else None,
    )


def declared_environment(env_var: str, dsn: str) -> Dict[str, str]:
    """The only environment a declared command is given.

    The preflight runs on an operator's machine that holds prod-admin and
    cloud credentials. A project's declared boot command needs a shell, its
    own package tooling, the copy's DSN, and the restore point naming that
    copy's dump — and nothing else.
    """
    from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV

    env = {
        key: value
        for key, value in os.environ.items()
        if key in _PASSTHROUGH_ENV or key.startswith(_PASSTHROUGH_PREFIXES)
    }
    restore_point = os.environ.get(RESTORE_POINT_ENV)
    if restore_point:
        env[RESTORE_POINT_ENV] = restore_point
    env[env_var] = dsn
    return env


def redact_dsn(text: str, dsn: str) -> str:
    """*text* with the copy's DSN and every secret part of it removed."""
    from psycopg import conninfo

    redacted = text.replace(dsn, "<dsn>")
    try:
        parts = conninfo.conninfo_to_dict(dsn)
    except Exception:  # noqa: BLE001 - an unparseable DSN still has its verbatim form removed
        return redacted
    password = str(parts.get("password") or "")
    if password:
        redacted = redacted.replace(password, "<redacted>")
    return redacted


def run_declared(argv: Sequence[str], *, cwd: Path, env_var: str, dsn: str) -> None:
    """Run one declared command against one copy, or raise why it failed."""
    shown = redact_dsn(" ".join(argv), dsn)
    try:
        from yoke_core.domain.migration_rehearsal_copy_lock import run_child

        result = run_child(
            list(argv),
            cwd=str(cwd),
            env=declared_environment(env_var, dsn),
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise DeclaredCommandError(
            f"`{shown}` did not finish within {COMMAND_TIMEOUT_SECONDS}s"
        ) from exc
    except OSError as exc:
        raise DeclaredCommandError(
            f"`{shown}` could not start from {cwd}: {exc}. Correct the model's "
            "fleet command or run the preflight where its tools are installed."
        ) from exc
    if result.returncode != 0:
        output = redact_dsn((result.stderr or result.stdout or "").strip(), dsn)
        raise DeclaredCommandError(
            f"`{shown}` exited {result.returncode}: {output[-_OUTPUT_TAIL_CHARS:]}"
        )


__all__ = [
    "COMMAND_TIMEOUT_SECONDS",
    "DeclaredCommandError",
    "declared_environment",
    "declared_plan",
    "redact_dsn",
    "run_declared",
]
