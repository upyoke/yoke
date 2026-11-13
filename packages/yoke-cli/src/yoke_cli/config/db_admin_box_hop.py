"""The SSH hop a box-mode db-admin profile uses to reach its environment's VM.

A box environment's Postgres runs in a Lima VM (``yoke-<env>``) on a Mac host
(``environments.settings.servers[0].mac_host``). ``hosts.origin`` is the
public relay, not that VM, so the profile tunnels through a Yoke-owned ssh
config instead: ``~/.yoke/ssh/config`` holds a ``yoke-<env>-box`` alias whose
ProxyCommand logs in to the Mac host through the file's own
``yoke-<env>-mac-host`` stanza (:mod:`yoke_cli.config.db_admin_box_mac_host`)
and connects ``nc`` to the VM's ssh port, which Lima picks anew at each VM start
and so is looked up on every connect.

:func:`ensure` makes the hop work from this machine: it creates the operator
key when the machine has none, authorizes it for the VM user over the Mac
host's ``limactl shell``, pins the VM's host key read through that same
authenticated shell (never trust on first use), and writes the alias. It
never touches ``~/.ssh``.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config import schema as contract
from yoke_contracts.machine_config import secret_files as machine_secrets
from yoke_contracts.machine_config.directories import create_private_directory
from yoke_cli.config import db_admin_box_mac_host as mac_leg
from yoke_cli.config.db_admin_setup_errors import DbAdminSetupError
from yoke_cli.config.db_admin_setup_report import _path_ref

SSH_DIR_NAME = "ssh"
REMOTE_TIMEOUT_SECONDS = 120
HOST_KEY_MARK = "@@yoke-box-host-key@@ "
# Same place ops/mac-host/install.sh keeps its VMs and pinned limactl.
LIMACTL = 'L=$(ls -d "$HOME"/yoke-boxes/lima-*/bin/limactl | tail -1)'
LIMA_HOME = 'LIMA_HOME="$HOME/yoke-boxes/lima"'
# Type and key only; the comment may be anything (a custody key's often is).
_PUBLIC_KEY = re.compile(r"^(ssh-ed25519 [A-Za-z0-9+/]+={0,2})(?:\s.*)?$")
_HOST_KEY = re.compile(r"^ssh-ed25519 [A-Za-z0-9+/=]+")


def alias(env_name: str) -> str:
    return f"yoke-{env_name}-box"


def host_key_alias(env_name: str) -> str:
    return f"yoke-{env_name}-mini-vm"


def vm_name(env_name: str) -> str:
    return f"yoke-{env_name}"


def ssh_dir() -> Path:
    return machine_config.yoke_home() / SSH_DIR_NAME


def config_path() -> Path:
    return ssh_dir() / "config"


def known_hosts_path() -> Path:
    return ssh_dir() / "known_hosts"


def key_path(env: Any) -> Path:
    name = f"{env.project}-{env.env_name}-box-operator-ssh-key"
    return machine_config.yoke_home() / contract.SECRETS_DIR_NAME / name


def mac_host(env: Any) -> str:
    """The Mac host login (``USER@HOST``), or a refusal naming the setting."""
    user, host = mac_leg.login(env)
    return f"{user}@{host}"


def proxy_command(env: Any) -> str:
    """ssh to the Mac host's Yoke alias, then nc to the VM's current Lima port."""
    lookup = (
        f'{LIMACTL}; exec nc 127.0.0.1 "$({LIMA_HOME} "$L" list '
        f'{vm_name(env.env_name)} --format "{{{{.SSHLocalPort}}}}")"'
    )
    return _mac_ssh(env, lookup)


def _mac_ssh(env: Any, remote: str) -> str:
    config = shlex.quote(str(config_path()))
    return f"ssh -F {config} {mac_leg.alias(env.env_name)} {shlex.quote(remote)}"


def tunnel_fields(env: Any) -> dict[str, str]:
    """The profile's tunnel keys that route through the hop."""
    return {
        "bastion": alias(env.env_name),
        "identity_file": str(key_path(env)),
        "ssh_config": str(config_path()),
    }


def plan_steps(env: Any) -> list[dict[str, str]]:
    return [
        {"action": "ensure-box-operator-key", "target": _path_ref(key_path(env))},
        {
            "action": "pin-mac-host-key",
            "target": f"{mac_host(env)} {mac_leg.fingerprint(env)}",
        },
        {
            "action": "authorize-box-operator-key",
            "target": f"{mac_host(env)} {vm_name(env.env_name)} {env.ssh_user}",
        },
        {"action": "pin-box-host-key", "target": _path_ref(known_hosts_path())},
        {"action": "write-box-ssh-config", "target": _path_ref(config_path())},
    ]


def ensure(env: Any) -> dict[str, Any]:
    """Make the hop work from this machine; return a report without secrets."""
    mac_leg.check_settings(env)
    host = mac_host(env)
    key = key_path(env)
    created = _ensure_key(env, key)
    found = _PUBLIC_KEY.match(_public_key(key))
    if found is None:
        raise DbAdminSetupError(
            f"box_operator_key_invalid: {_path_ref(Path(f'{key}.pub'))} does "
            "not start with an ssh-ed25519 type and key; restore that public "
            f"half from the private key (`ssh-keygen -y -f {_path_ref(key)}`), "
            "then rerun"
        )
    public = found.group(1)
    mac_key = mac_leg.pinned_host_key(env, _run)
    create_private_directory(ssh_dir())
    _upsert_known_host(mac_leg.alias(env.env_name), mac_key)
    _upsert_host_blocks(env)
    host_key = _authorize_and_read_host_key(env, host, public)
    _upsert_known_host(host_key_alias(env.env_name), host_key)
    return {
        "ssh_config": _path_ref(config_path()),
        "alias": alias(env.env_name),
        "mac_host": host,
        "mac_host_alias": mac_leg.alias(env.env_name),
        "operator_key": _path_ref(key),
        "operator_key_created": created,
        "host_key_alias": host_key_alias(env.env_name),
    }


def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False, **kwargs)


def _ensure_key(env: Any, key: Path) -> bool:
    if key.exists():
        return False
    machine_secrets.secrets_dir()
    comment = f"yoke-{env.env_name}-operator-box-key"
    result = _run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(key)]
    )
    if result.returncode != 0 or not key.exists():
        raise DbAdminSetupError(
            f"box_operator_key_create_failed: ssh-keygen could not create "
            f"{_path_ref(key)} (rc={result.returncode}): "
            f"{(result.stderr or '').strip()}; fix ssh-keygen, then rerun"
        )
    key.chmod(0o600)
    return True


def _public_key(key: Path) -> str:
    """The key's public half: its ``.pub`` file, else derived from the key."""
    pub = Path(f"{key}.pub")
    if pub.exists():
        return pub.read_text(encoding="utf-8").strip()
    result = _run(["ssh-keygen", "-y", "-f", str(key)])
    if result.returncode != 0:
        raise DbAdminSetupError(
            f"box_operator_key_unreadable: ssh-keygen could not read "
            f"{_path_ref(key)} (rc={result.returncode}): "
            f"{(result.stderr or '').strip()}; move the key aside, then rerun so "
            "setup creates a new one"
        )
    return result.stdout.strip()


def _vm_script(user: str, public: str) -> str:
    """Runs in the VM as the Lima user: authorize the key, print the host key."""
    return "\n".join(
        [
            "set -eu",
            f"U={shlex.quote(user)}",
            f"K={shlex.quote(public)}",
            'H=$(getent passwd "$U" | cut -d: -f6)',
            '[ -n "$H" ] || { echo "VM user $U does not exist" >&2; exit 4; }',
            'G=$(id -gn "$U")',
            'sudo -n install -d -m 700 -o "$U" -g "$G" "$H/.ssh"',
            'F="$H/.ssh/authorized_keys"',
            'sudo -n touch "$F"',
            # A line already carrying this type and key (any comment) counts.
            'sudo -n awk -v k="$K" \'$1" "$2==k{f=1} END{exit (f==0)}\' "$F" '
            '|| printf \'%s\\n\' "$K" | sudo -n tee -a "$F" >/dev/null',
            'sudo -n chown "$U:$G" "$F"',
            'sudo -n chmod 600 "$F"',
            f'printf \'{HOST_KEY_MARK}%s\\n\' "$(cat /etc/ssh/ssh_host_ed25519_key.pub)"',
            "",
        ]
    )


def _authorize_and_read_host_key(env: Any, host: str, public: str) -> str:
    vm = vm_name(env.env_name)
    remote = (
        f"{LIMACTL}; export {LIMA_HOME}; "
        f'exec "$L" --tty=false shell --workdir / {vm} sh -s'
    )
    setting = f"servers[0].mac_host ({host}) of {env.project}/{env.env_name}"
    mac_alias = mac_leg.alias(env.env_name)
    try:
        result = _run(
            ["ssh", "-F", str(config_path()), "-o", "ConnectTimeout=15", mac_alias, remote],
            input=_vm_script(str(env.ssh_user), public),
            timeout=REMOTE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise DbAdminSetupError(
            f"box_mac_host_timeout: no answer from {setting} within "
            f"{REMOTE_TIMEOUT_SECONDS}s; check that the Mac host is up and "
            "reachable, then rerun"
        ) from None
    detail = (result.stderr or "").strip()
    if result.returncode == 255:
        raise DbAdminSetupError(
            f"box_mac_host_unreachable: could not ssh to {setting} through "
            f"{mac_alias} in {_path_ref(config_path())}: {detail}; check "
            "servers[0].mac_host and servers[0].mac_host_ssh_key_path (the key "
            "must be authorized on the Mac host), then rerun"
        )
    found = [
        line[len(HOST_KEY_MARK):].strip()
        for line in (result.stdout or "").splitlines()
        if line.startswith(HOST_KEY_MARK)
    ]
    host_key = _HOST_KEY.match(found[-1]) if found else None
    if result.returncode != 0 or host_key is None:
        raise DbAdminSetupError(
            f"box_operator_key_authorize_failed: authorizing the operator key "
            f"for {env.ssh_user} in VM {vm} on {host} failed "
            f"(rc={result.returncode}): {detail}; check that VM {vm} runs "
            f"(`limactl list {vm}` on the Mac host), then rerun"
        )
    return host_key.group(0)


def _write_private(path: Path, text: str) -> None:
    machine_secrets._refuse_unisolated_test_write(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def _upsert_known_host(name: str, host_key: str) -> None:
    path = known_hosts_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    kept = [line for line in lines if line.split(" ", 1)[0] != name]
    _write_private(path, "\n".join([*kept, f"{name} {host_key}"]) + "\n")


def _host_block(env: Any) -> str:
    return "\n".join(
        [
            f"Host {alias(env.env_name)}",
            f"  User {env.ssh_user}",
            f'  IdentityFile "{key_path(env)}"',
            "  IdentitiesOnly yes",
            f"  HostKeyAlias {host_key_alias(env.env_name)}",
            f'  UserKnownHostsFile "{known_hosts_path()}"',
            "  StrictHostKeyChecking yes",
            f"  ProxyCommand {proxy_command(env)}",
        ]
    )


def _upsert_host_blocks(env: Any) -> None:
    """Replace this environment's two ``Host`` blocks; keep every other one."""
    path = config_path()
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    blocks = [b.strip() for b in re.split(r"(?m)^(?=Host )", text) if b.strip()]
    blocks = [b for b in blocks if b.startswith("Host ")]
    ours = [mac_leg.host_block(env, str(known_hosts_path())), _host_block(env)]
    names = {block.splitlines()[0] for block in ours}
    blocks = [b for b in blocks if b.splitlines()[0] not in names]
    header = "# Written by `yoke dev db-admin setup`; rerun it instead of editing."
    _write_private(path, "\n\n".join([header, *sorted([*blocks, *ours])]) + "\n")


__all__ = [
    "alias",
    "config_path",
    "ensure",
    "host_key_alias",
    "key_path",
    "known_hosts_path",
    "mac_host",
    "plan_steps",
    "proxy_command",
    "tunnel_fields",
    "vm_name",
]
