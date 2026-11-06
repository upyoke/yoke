"""Keep the validation provisioner's one durable output outside source isolation."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Mapping, Sequence

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.machine_config.paths import HOME_ENV
from yoke_contracts.machine_config.schema import SECRETS_DIR_NAME
from yoke_core.domain import migration_validation_binding as binding
from yoke_core.tools._source_pythonpath import AMBIENT_PYTHON_NAMES

PROVISION_MODULE = "runtime.api.tools.authority_validation_copy"


def persist(command: Sequence[str], child_env: Mapping[str, str]) -> int:
    """Publish only a successful provisioner's binding, never arbitrary edits."""
    if (
        len(command) != 3
        or Path(command[0]).name not in AMBIENT_PYTHON_NAMES
        or list(command[1:]) != ["-m", PROVISION_MODULE]
    ):
        return 0
    target = binding.binding_file(binding.YOKE_VALIDATION_DSN_ENV)
    source = (
        Path(child_env.get(HOME_ENV) or target.parent.parent)
        / SECRETS_DIR_NAME
        / target.name
    )
    if source.resolve() == target.resolve():
        return 0
    try:
        value = source.read_text(encoding="utf-8")
        binding.write_binding(binding.YOKE_VALIDATION_DSN_ENV, value)
    except (OSError, UnicodeError, RuntimeError):
        print(
            compose_refusal(
                "validation_binding_persist_failed: provisioning completed, but "
                f"its binding could not be saved to {target}",
                recovery="repair access to the machine secrets directory and "
                "rerun the provisioning command; rehearsal is not ready until "
                "the binding is saved",
            ),
            file=sys.stderr,
        )
        return 1
    print(f"validation binding persisted: {target}")
    return 0
