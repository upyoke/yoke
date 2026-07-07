"""Machine-local capability secret path contract."""

from __future__ import annotations

from pathlib import Path

CAPABILITY_SECRETS_DIR_NAME = "capability-secrets"
AWS_ADMIN_CAPABILITY = "aws-admin"
AWS_ADMIN_SECRET_KEYS = frozenset({
    "access_key_id",
    "secret_access_key",
    "session_token",
})
SSH_CAPABILITY = "ssh"
SSH_PRIVATE_KEY_SECRET_KEY = "private_key"
SSH_SECRET_KEYS = frozenset({SSH_PRIVATE_KEY_SECRET_KEY})
MACHINE_LOCAL_SECRET_KEYS_BY_CAPABILITY = {
    AWS_ADMIN_CAPABILITY: AWS_ADMIN_SECRET_KEYS,
    SSH_CAPABILITY: SSH_SECRET_KEYS,
}


def machine_local_capability_secret_keys(cap_type: str) -> frozenset[str]:
    """Return machine-local secret keys for a capability type."""
    return MACHINE_LOCAL_SECRET_KEYS_BY_CAPABILITY.get(cap_type, frozenset())


def is_machine_local_capability_secret(
    cap_type: str,
    key: str | None = None,
) -> bool:
    """Return whether a capability secret is owned by the local machine."""
    allowed = machine_local_capability_secret_keys(cap_type)
    if not allowed:
        return False
    return key is None or key in allowed


def capability_secret_relative_path(
    project_slug: str,
    cap_type: str,
    key: str,
) -> Path:
    """Return the path under ``~/.yoke/secrets`` for a local secret."""
    if not is_machine_local_capability_secret(cap_type, key):
        raise ValueError(
            f"{cap_type}.{key} is not a machine-local capability secret"
        )
    return (
        Path(CAPABILITY_SECRETS_DIR_NAME)
        / safe_secret_component(project_slug, "project")
        / safe_secret_component(cap_type, "capability")
        / safe_secret_component(key, "secret key")
    )


def capability_secret_directory_relative_path(
    project_slug: str,
    cap_type: str,
) -> Path:
    """Return the directory under ``~/.yoke/secrets`` for a capability."""
    if not is_machine_local_capability_secret(cap_type):
        raise ValueError(f"{cap_type} is not a machine-local capability")
    return (
        Path(CAPABILITY_SECRETS_DIR_NAME)
        / safe_secret_component(project_slug, "project")
        / safe_secret_component(cap_type, "capability")
    )


def safe_secret_component(raw: str, label: str) -> str:
    """Normalize a user/domain label for deterministic secret paths."""
    safe = "".join(
        char if char.isalnum() or char in "._-" else "_"
        for char in str(raw or "").strip()
    ).strip("._-")
    if not safe:
        raise ValueError(f"{label} must include a filesystem-safe label")
    return safe


__all__ = [
    "AWS_ADMIN_CAPABILITY",
    "AWS_ADMIN_SECRET_KEYS",
    "CAPABILITY_SECRETS_DIR_NAME",
    "MACHINE_LOCAL_SECRET_KEYS_BY_CAPABILITY",
    "SSH_CAPABILITY",
    "SSH_PRIVATE_KEY_SECRET_KEY",
    "SSH_SECRET_KEYS",
    "capability_secret_directory_relative_path",
    "capability_secret_relative_path",
    "is_machine_local_capability_secret",
    "machine_local_capability_secret_keys",
    "safe_secret_component",
]
