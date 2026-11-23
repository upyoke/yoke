"""The Mac-host leg of the box hop, defined in the Yoke-owned ssh config.

Nobody edits ``~/.ssh`` and a sandboxed agent cannot read it. So setup writes a
``yoke-<env>-mac-host`` stanza into ``~/.yoke/ssh/config`` that logs in with a
per-machine key, ``~/.yoke/secrets/<project>-<env>-mac-host-ssh-key``, from two
environment settings in ``environments.settings.servers[0]``:

- ``mac_host``: the ssh login, ``USER@HOST``;
- ``mac_host_key_fingerprint``: the ``SHA256:...`` fingerprint of the Mac
  host's ssh host key.

The host key is scanned and accepted only when its fingerprint equals the
declared one, then pinned in ``~/.yoke/ssh/known_hosts`` under the stanza's
``HostKeyAlias``; nothing is trusted on first use. The host authorizes the key
for a forced command, and :func:`probe` proves that before the config changes.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config import schema as contract
from yoke_cli.config.db_admin_setup_errors import DbAdminSetupError
from yoke_cli.config.db_admin_setup_report import _path_ref

SCAN_TIMEOUT_SECONDS = 15
PROBE_TIMEOUT_SECONDS = 30
VM_USER = "ubuntu"
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


def key_path(env: Any) -> Path:
    name = f"{env.project}-{env.env_name}-mac-host-ssh-key"
    return machine_config.yoke_home() / contract.SECRETS_DIR_NAME / name


def fingerprint(env: Any) -> str:
    return _required(env, "mac_host_key_fingerprint", "SHA256:...", _FINGERPRINT)


def check_settings(env: Any) -> None:
    """Refuse before any change when a Mac-host setting is missing."""
    login(env)
    fingerprint(env)
    if env.ssh_user != VM_USER:
        raise DbAdminSetupError(
            f"box_ssh_user_unsupported: the ssh user of {env.project}/{env.env_name} "
            f"is {env.ssh_user!r}, but the Mac-host hop supports only {VM_USER!r}, "
            f"the Lima guest user; set servers[0].ssh_user to {VM_USER}, then rerun"
        )


def host_block(env: Any, known_hosts: str) -> str:
    user, host = login(env)
    name = alias(env.env_name)
    return "\n".join(
        [
            f"Host {name}",
            f"  HostName {host}",
            f"  User {user}",
            f'  IdentityFile "{Path(key_path(env)).as_posix()}"',
            "  IdentitiesOnly yes",
            f"  HostKeyAlias {name}",
            f'  UserKnownHostsFile "{Path(known_hosts).as_posix()}"',
            "  StrictHostKeyChecking yes",
            "  BatchMode yes",
        ]
    )


def probe(env: Any, known_hosts: str, run: Runner) -> None:
    """Prove the host runs the hop's forced command for this key, or refuse."""
    user, host = login(env)
    key = key_path(env)
    name = alias(env.env_name)
    argv = [
        "ssh", "-F", "none", "-o", "IdentitiesOnly=yes", "-i", str(key),
        "-o", f"HostKeyAlias={name}", "-o", f"UserKnownHostsFile={known_hosts}",
        "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15", f"{user}@{host}", "probe",
    ]
    login_ref = f"{user}@{host}"
    try:
        result = run(argv, timeout=PROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise DbAdminSetupError(
            f"box_mac_host_timeout: no answer from {login_ref} within "
            f"{PROBE_TIMEOUT_SECONDS}s; check that the Mac host is up and "
            "reachable, then rerun"
        ) from None
    detail = (result.stderr or "").strip()
    if result.returncode == 0 and (result.stdout or "").strip() == "ok":
        return
    if result.returncode == 255 and "Permission denied" in detail:
        raise DbAdminSetupError(
            f"box_mac_host_key_unauthorized: {login_ref} does not accept this "
            f"machine's key; add the public half {_path_ref(key)}.pub to the host's "
            "hop key list, then rerun"
        )
    if result.returncode == 255:
        raise DbAdminSetupError(
            f"box_mac_host_unreachable: could not ssh to {login_ref} "
            f"({_setting(env, 'mac_host')}): {detail}; check that the Mac host is "
            "up and reachable from this machine, then rerun"
        )
    raise DbAdminSetupError(
        f"box_mac_host_command_missing: {login_ref} accepted this machine's key but "
        f"did not answer the hop's probe (rc={result.returncode}): {detail}; the "
        "host's hop command is not installed for this key; install it on the "
        "Mac host, then rerun"
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
    "probe",
]
