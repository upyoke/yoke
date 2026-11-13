"""The Mac-host leg of the box hop, defined in the Yoke-owned ssh config.

The operator's plain ``ssh USER@HOST`` to the Mac host may not work (its host
key may be pinned under another name, its key may not be a default identity),
and nobody edits ``~/.ssh``. So setup writes a ``yoke-<env>-mac-host`` stanza
into ``~/.yoke/ssh/config`` from three environment settings that sit together
in ``environments.settings.servers[0]``:

- ``mac_host``: the ssh login, ``USER@HOST``;
- ``mac_host_ssh_key_path``: the identity file that login uses;
- ``mac_host_key_fingerprint``: the ``SHA256:...`` fingerprint of the Mac
  host's ssh host key.

The host key is scanned and accepted only when its fingerprint equals the
declared one, then pinned in ``~/.yoke/ssh/known_hosts`` under the stanza's
``HostKeyAlias``; nothing is trusted on first use.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from typing import Any, Callable

from yoke_cli.config.db_admin_setup_errors import DbAdminSetupError

SCAN_TIMEOUT_SECONDS = 15
_MAC_HOST = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$")
_FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def alias(env_name: str) -> str:
    return f"yoke-{env_name}-mac-host"


def _setting(env: Any, key: str) -> str:
    return f"environments.settings.servers[0].{key} of {env.project}/{env.env_name}"


def _merge_hint(env: Any, key: str, example: str) -> str:
    return (
        f"`yoke projects environment settings merge --project {env.project} "
        f"--environment {env.env_name} --set servers.0.{key}={example}`"
    )


def _required(env: Any, key: str, example: str, pattern: re.Pattern[str] | None) -> str:
    value = str(getattr(env, key, "") or "").strip()
    if not value:
        raise DbAdminSetupError(
            f"box_{key}_missing: {_setting(env, key)} is not set, so setup cannot "
            f"reach the box VM's Mac host; set it with {_merge_hint(env, key, example)}, "
            "then rerun"
        )
    if pattern is not None and not pattern.match(value):
        raise DbAdminSetupError(
            f"box_{key}_invalid: {_setting(env, key)} is {value!r}, not {example}; "
            "correct it, then rerun"
        )
    return value


def login(env: Any) -> tuple[str, str]:
    """``(user, host)`` of the Mac host login, or a refusal naming the setting."""
    value = _required(env, "mac_host", "USER@HOST", _MAC_HOST)
    user, host = value.split("@", 1)
    return user, host


def key_path(env: Any) -> str:
    return os.path.expanduser(
        _required(env, "mac_host_ssh_key_path", "~/.ssh/KEY", None)
    )


def fingerprint(env: Any) -> str:
    return _required(env, "mac_host_key_fingerprint", "SHA256:...", _FINGERPRINT)


def check_settings(env: Any) -> None:
    """Refuse before any change when a Mac-host setting is missing."""
    login(env)
    key_path(env)
    fingerprint(env)


def host_block(env: Any, known_hosts: str) -> str:
    user, host = login(env)
    name = alias(env.env_name)
    return "\n".join(
        [
            f"Host {name}",
            f"  HostName {host}",
            f"  User {user}",
            f'  IdentityFile "{key_path(env)}"',
            "  IdentitiesOnly yes",
            f"  HostKeyAlias {name}",
            f'  UserKnownHostsFile "{known_hosts}"',
            "  StrictHostKeyChecking yes",
            "  BatchMode yes",
        ]
    )


def pinned_host_key(env: Any, run: Runner) -> str:
    """Scan the Mac host and return the one key matching the declared fingerprint."""
    _user, host = login(env)
    wanted = fingerprint(env)
    setting = _setting(env, "mac_host_key_fingerprint")
    try:
        scan = run(
            ["ssh-keyscan", "-T", str(SCAN_TIMEOUT_SECONDS), host],
            timeout=SCAN_TIMEOUT_SECONDS + 5,
        )
    except subprocess.TimeoutExpired:
        scan = subprocess.CompletedProcess([], 1, "", "timed out")
    keys = [
        line.split(" ", 1)[1].strip()
        for line in (scan.stdout or "").splitlines()
        if line and not line.startswith("#") and " " in line
    ]
    if not keys:
        raise DbAdminSetupError(
            f"box_mac_host_unreachable: ssh-keyscan of {host} "
            f"({_setting(env, 'mac_host')}) returned no host key: "
            f"{(scan.stderr or '').strip()}; check that the Mac host is up and "
            "reachable from this machine, then rerun"
        )
    for key in keys:
        if _key_fingerprint(key, run) == wanted:
            return key
    raise DbAdminSetupError(
        f"box_mac_host_key_mismatch: no host key {host} offers has the fingerprint "
        f"{wanted} declared in {setting}; confirm the Mac host's key on the Mac "
        "itself (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`), correct the "
        "setting, then rerun"
    )


def _key_fingerprint(key: str, run: Runner) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".pub", delete=False) as handle:
        handle.write(f"{key}\n")
        path = handle.name
    try:
        result = run(["ssh-keygen", "-l", "-E", "sha256", "-f", path])
    finally:
        os.unlink(path)
    parts = (result.stdout or "").split()
    return parts[1] if result.returncode == 0 and len(parts) > 1 else ""


__all__ = [
    "alias",
    "check_settings",
    "fingerprint",
    "host_block",
    "key_path",
    "login",
    "pinned_host_key",
]
