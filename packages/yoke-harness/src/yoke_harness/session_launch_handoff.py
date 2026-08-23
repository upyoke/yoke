"""Owner-only launch attestation handoff into the first native hook."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import stat
import time
from typing import Mapping
from uuid import UUID

from yoke_cli.config import machine_config


LAUNCH_CONTEXT_ENV = "YOKE_SESSION_LAUNCH_CONTEXT"
HANDOFF_DIRECTORY_NAME = "session-launch-handoffs"
HANDOFF_TTL_SECONDS = 2 * 60 * 60
_MAX_HANDOFF_BYTES = 4096


@dataclass(frozen=True)
class LaunchProjection:
    launch_id: str
    binding_id: str | None = None


def _identifier(value: object) -> str | None:
    try:
        return str(UUID(str(value or "").strip()))
    except (AttributeError, TypeError, ValueError):
        return None


def _directory(state_dir: Path | None = None) -> Path:
    root = state_dir or machine_config.cache_dir()
    directory = root / HANDOFF_DIRECTORY_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    return directory


def _handoff_path(binding_id: str, state_dir: Path | None = None) -> Path:
    return _directory(state_dir) / f"{binding_id}.json"


def _delivered_path(launch_id: str, state_dir: Path | None = None) -> Path:
    return _directory(state_dir) / f"{launch_id}.delivered"


def _write_owner_only(path: Path, payload: Mapping[str, object]) -> bool:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = None
    try:
        descriptor = os.open(temporary, flags, 0o600)
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(body) > _MAX_HANDOFF_BYTES:
            return False
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
        return True
    except OSError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_owner_only(path: Path, *, now: float) -> dict[str, object] | None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or now - info.st_mtime > HANDOFF_TTL_SECONDS
            or info.st_size > _MAX_HANDOFF_BYTES
        ):
            return None
        body = os.read(descriptor, _MAX_HANDOFF_BYTES + 1)
        if len(body) > _MAX_HANDOFF_BYTES:
            return None
        payload = json.loads(body)
        return payload if isinstance(payload, dict) else None
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    finally:
        os.close(descriptor)


def stage_launch_attestation(
    launch_id: str,
    attestation: str,
    *,
    binding_id: str | None = None,
    state_dir: Path | None = None,
) -> bool:
    """Persist one attestation without placing it in native argv or output."""
    launch = _identifier(launch_id)
    binding = _identifier(binding_id or launch_id)
    token = str(attestation or "").strip()
    if launch is None or binding is None or not token or len(token) > 1024:
        return False
    return _write_owner_only(
        _handoff_path(binding, state_dir),
        {
            "launch_id": launch,
            "binding_id": binding,
            "attestation": token,
            "staged_at": int(time.time()),
        },
    )


def _environment_context(environ: Mapping[str, str]) -> dict[str, object] | None:
    try:
        payload = json.loads(environ.get(LAUNCH_CONTEXT_ENV, ""))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def project_launch_attestation(
    payload: dict[str, object],
    *,
    environ: Mapping[str, str] = os.environ,
    state_dir: Path | None = None,
    now: float | None = None,
) -> LaunchProjection | None:
    """Project only a local authenticated side channel into ``yoke_launch``."""
    payload.pop("yoke_launch", None)
    current = time.time() if now is None else now
    raw = _environment_context(environ)
    binding: str | None = None
    if raw is None:
        binding = _identifier(payload.get("session_id"))
        if binding is None:
            return None
        raw = _read_owner_only(_handoff_path(binding, state_dir), now=current)
    if raw is None:
        return None
    launch = _identifier(raw.get("launch_id"))
    token = raw.get("attestation")
    if launch is None or not isinstance(token, str) or not token.strip():
        return None
    delivered = _read_owner_only(_delivered_path(launch, state_dir), now=current)
    if delivered is not None:
        return None
    payload["yoke_launch"] = {
        "launch_id": launch,
        "attestation": token.strip(),
    }
    return LaunchProjection(launch, binding)


def mark_launch_attestation_delivered(
    projection: LaunchProjection,
    *,
    state_dir: Path | None = None,
) -> None:
    """Suppress replay only after hook output proves instruction delivery."""
    _write_owner_only(
        _delivered_path(projection.launch_id, state_dir),
        {"launch_id": projection.launch_id, "delivered_at": int(time.time())},
    )
    if projection.binding_id:
        try:
            _handoff_path(projection.binding_id, state_dir).unlink(missing_ok=True)
        except OSError:
            pass


def launch_delivery_rendered(text: str, projection: LaunchProjection) -> bool:
    return f"YOKE_SESSION_LAUNCH:{projection.launch_id}:" in text


__all__ = [
    "HANDOFF_DIRECTORY_NAME",
    "HANDOFF_TTL_SECONDS",
    "LAUNCH_CONTEXT_ENV",
    "LaunchProjection",
    "launch_delivery_rendered",
    "mark_launch_attestation_delivered",
    "project_launch_attestation",
    "stage_launch_attestation",
]
