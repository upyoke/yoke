"""Deploy database SSH forwards use the shared connected-environment lifecycle."""

from __future__ import annotations

from yoke_core.domain import connected_env_tunnel_lifecycle as lifecycle
from yoke_core.domain.connected_env_readiness_connector import TunnelSpec


def open_db_tunnel(runner, env, forward_spec: str, *, timeout: int = 30) -> None:
    host, port, destination = forward_spec.split(":", 2)
    remote, remote_port = destination.rsplit(":", 1)
    spec = TunnelSpec(
        local_host=host,
        local_port=int(port),
        bastion=env.ssh_target,
        identity_file=env.ssh_key_path,
        remote_host=remote,
        remote_port=int(remote_port),
    )
    # Reuse the same key/options/port-readiness path as connected environments.
    argv = lifecycle._build_ssh_argv(spec)
    argv[argv.index("-L") + 1] = forward_spec
    runner.start_forward(argv, host=host, port=int(port), timeout=timeout)


def close_db_tunnel(runner, forward_spec: str, *, timeout: int = 10) -> None:
    runner.stop_forward(forward_spec, timeout=timeout)


def stop_forward(forward_spec: str, *, timeout: int) -> None:
    matches = [
        info.pid
        for info in lifecycle.process_command_lines()
        if info.cmdline
        and lifecycle.os.path.basename(info.cmdline[0]).lower() in {"ssh", "ssh.exe"}
        and any(
            word == "-L"
            and index + 1 < len(info.cmdline)
            and info.cmdline[index + 1] == forward_spec
            or word == "-L" + forward_spec
            for index, word in enumerate(info.cmdline)
        )
    ]
    lifecycle._terminate_pids(matches, timeout=timeout)
