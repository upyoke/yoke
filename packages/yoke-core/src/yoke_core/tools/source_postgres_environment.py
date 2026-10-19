"""Preserve machine-wide test resources when commands isolate their settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from yoke_contracts.machine_config.paths import CONFIG_FILE_ENV, HOME_ENV
from yoke_contracts.machine_config.scratch_roots import fallback_scratch_root
from yoke_core.domain.postgres_binaries import POSTGRES_VERSION


def shared_postgres_environment(env: Mapping[str, str]) -> dict[str, str]:
    """Resolve before replacing HOME, machine home or the evidence root.

    Only immutable binaries and the disposable test cluster are shared;
    configuration and credentials remain isolated by their existing owner.
    """
    result = dict(env)
    home = Path(env.get(HOME_ENV) or Path(env.get("HOME", str(Path.home()))) / ".yoke")
    selected = home / "config.json"
    if not env.get(HOME_ENV) and env.get(CONFIG_FILE_ENV):
        selected = Path(env[CONFIG_FILE_ENV]).expanduser()
        if not selected.is_absolute():
            selected = home / selected
    if not env.get("YOKE_PG_CLUSTER_ROOT"):
        try:
            payload = json.loads(selected.read_text()) if selected.is_file() else {}
            if not isinstance(payload, dict):
                raise ValueError("machine config must contain an object")
        except (ValueError, OSError) as exc:
            raise OSError(
                f"cannot read test resource settings from {selected}; repair its JSON and read permissions"
            ) from exc
        scratch = env.get("YOKE_SCRATCH_ROOT") or payload.get("temp_root")
        root = Path(scratch).expanduser() if scratch else fallback_scratch_root()
        result["YOKE_PG_CLUSTER_ROOT"] = str(root.absolute() / "yoke-pgtest-cluster")
    binaries = home.absolute() / "postgres" / POSTGRES_VERSION / "bin"
    if not result.get("YOKE_PG_BIN_DIR") and (binaries / "initdb").is_file():
        result["YOKE_PG_BIN_DIR"] = str(binaries)
    return result
