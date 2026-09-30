"""Materialize bounded descriptor-handoff secrets into the private tmpfs."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
from typing import Mapping

from yoke_contracts.machine_config.directories import create_private_directory
from yoke_contracts.self_host_handoff import CORE_SECRETS

SELF_HOST_RUNTIME_SECRETS_DIR = Path("/dev/shm/yoke-runtime-secrets")


class SelfHostServerBootstrapError(RuntimeError):
    """Self-host secret materialization or privilege drop was unsafe."""


def materialize_self_host_runtime_secrets(
    env: Mapping[str, str],
    *,
    payloads: Mapping[str, bytes],
    target_dir: Path = SELF_HOST_RUNTIME_SECRETS_DIR,
    runtime_uid: int,
    runtime_gid: int,
) -> tuple[dict[str, str], tuple[Path, ...]]:
    """Write only allowlisted, host-opened inputs; never open host mounts."""
    expected = {spec.env_name for spec in CORE_SECRETS if env.get(spec.env_name)}
    if set(payloads) != expected or not all(
        spec.env_name in payloads for spec in CORE_SECRETS if spec.required
    ):
        raise SelfHostServerBootstrapError(
            "self_host_handoff_inputs_invalid: configured secrets and handoff differ; "
            "restart with `yoke self-host init --protect-existing --start`"
        )
    if (runtime_uid, runtime_gid) != (os.geteuid(), os.getegid()):
        raise SelfHostServerBootstrapError(
            "self_host_handoff_identity_invalid: drop to the runtime user before materialization"
        )
    rewritten = dict(env)
    targets = []
    try:
        create_private_directory(target_dir)
        if not stat.S_ISDIR(target_dir.lstat().st_mode):
            raise ValueError("runtime target is not a real directory")
        info = target_dir.stat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("runtime directory must be current-owner mode 0700")
        for spec in CORE_SECRETS:
            if spec.env_name not in payloads:
                continue
            payload = payloads[spec.env_name]
            if not payload or len(payload) > spec.max_bytes:
                raise ValueError(f"invalid size for {spec.env_name}")
            target = target_dir / spec.runtime_name
            descriptor, temporary = tempfile.mkstemp(dir=target_dir)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(payload)
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
            rewritten[spec.env_name] = str(target)
            targets.append(target)
    except (OSError, ValueError) as exc:
        raise SelfHostServerBootstrapError(
            "self_host_handoff_materialization_failed: private runtime inputs could "
            "not be prepared; inspect container logs and restart through self-host init --start"
        ) from exc
    return rewritten, tuple(targets)
