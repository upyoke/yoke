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
"""

from __future__ import annotations

import os
from pathlib import Path

#: Appended to a model's declared ``runner.config.connection_env_var``.
VALIDATION_ENV_SUFFIX = "_VALIDATION"

#: Extension of the machine-local binding file under ``~/.yoke/secrets``.
BINDING_FILE_SUFFIX = "dsn"


def validation_env_var(connection_env_var: str) -> str:
    """Return the validation binding name for a model's authority binding."""
    return f"{connection_env_var}{VALIDATION_ENV_SUFFIX}"


def binding_file(env_var: str) -> Path:
    """Return the machine-local file that may carry *env_var*'s DSN."""
    from yoke_cli.config.secrets import secret_path_no_create

    return secret_path_no_create(env_var, BINDING_FILE_SUFFIX)


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


def write_binding(env_var: str, dsn: str) -> Path:
    """Persist *dsn* as *env_var*'s owner-only machine-local binding."""
    from yoke_cli.config.secrets import replace_secret_file

    return replace_secret_file(binding_file(env_var), env_var, dsn)


__all__ = [
    "BINDING_FILE_SUFFIX",
    "VALIDATION_ENV_SUFFIX",
    "binding_file",
    "read_binding",
    "validation_env_var",
    "write_binding",
]
