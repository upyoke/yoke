"""Supervise one real self-host server for the Machine QA admission fixture.

Runs on the test machine under ``machine_qa_admission_host serve MODE``. It
starts the mode's disposable embedded Postgres cluster, then the unchanged
self-host server entrypoint on loopback. That first boot births the universe
and hands the owner's one-time token over the self-host private descriptor;
this process plays the bundle host: it saves the token owner-only, records
the approver machine config, and acknowledges. Company sign-in runs the stub
identity provider here for as long as the server lives.
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

from yoke_contracts.control_plane_locality import PG_DSN_ENV
from yoke_contracts.first_admin_name import ADMIN_NAME_ENV
from yoke_contracts.machine_config.paths import HOME_ENV as MACHINE_HOME_ENV
from yoke_contracts.self_host_bootstrap_output import (
    API_PUBLISH_ENV,
    FIRST_BOOT_TOKEN_FD_ENV,
    FIRST_BOOT_TOKEN_HOST_PATH_ENV,
)
from yoke_contracts.server_mode import SERVER_MODE_ENV, SERVER_MODE_SELF_HOST
from yoke_contracts.self_host_handoff import HANDOFF_ACK, HANDOFF_TIMEOUT_SECONDS

from yoke_core.domain.machine_qa_admission_host import (
    APPROVER_ENV,
    MODE_PORTS,
    OWNER_NAME,
    TEAMMATE_EMAIL,
    TEAMMATE_SUBJECT,
    AdmissionFixtureError,
    api_url,
    approver_home,
    mode_root,
    server_methods,
    universe_spec,
    write_private,
)

_MAX_TOKEN_BYTES = 4096


def receive_owner_token(host_end: socket.socket, token_path: Path) -> None:
    """Save the first boot's token owner-only, then acknowledge durable storage."""
    host_end.settimeout(HANDOFF_TIMEOUT_SECONDS)
    wire = bytearray()
    while not wire.endswith(b"\n"):
        chunk = host_end.recv(256)
        if not chunk or len(wire) > _MAX_TOKEN_BYTES:
            raise AdmissionFixtureError(
                "machine_admission_owner_token_missing: the server's first boot "
                "delivered no owner token; read server.log for the birth "
                "failure, then rerun the case."
            )
        wire.extend(chunk)
    write_private(token_path, wire.decode("utf-8"))
    host_end.sendall(HANDOFF_ACK)


def _company_sign_in(mode: str, env: dict[str, str]):
    from yoke_core.api.oidc_stub_provider import StubOidcProvider

    provider = StubOidcProvider(
        auto_approve_claims={
            "sub": TEAMMATE_SUBJECT,
            "email": TEAMMATE_EMAIL,
            "email_verified": True,
        }
    )
    secret = mode_root(mode) / "oidc-client-secret"
    write_private(secret, provider.client_secret + "\n")
    env.update(
        {
            "YOKE_OIDC_ISSUER": provider.issuer,
            "YOKE_OIDC_CLIENT_ID": provider.client_id,
            "YOKE_OIDC_CLIENT_SECRET_FILE": str(secret),
            "YOKE_OIDC_REDIRECT_URL": api_url(mode),
        }
    )
    return provider


def invite_teammate_identity() -> None:
    """As the owner, invite the teammate's company identity through the CLI.

    The owner's invite is the journey's precondition; the teammate's own
    sign-in and machine approval remain the steps under test.
    """
    environment = {key: value for key, value in os.environ.items() if key != "YOKE_ENV"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_cli.main",
            "invite",
            TEAMMATE_EMAIL,
            "--role",
            "operator",
        ],
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise AdmissionFixtureError(
            "machine_admission_teammate_invite_failed: the owner could not "
            f"invite {TEAMMATE_EMAIL} (exit {result.returncode}); read "
            "server.log, repair the server, then rerun the case.\n"
            + (result.stderr or result.stdout).strip()[-2000:]
        )


def run_server(mode: str) -> int:
    """Serve until terminated; always stop the cluster and the provider."""
    from yoke_cli.config import writer
    from yoke_core.domain import local_universe

    approver = approver_home(mode)
    approver.mkdir(mode=0o700, parents=True, exist_ok=True)
    spec = universe_spec(
        mode, bin_dir=local_universe.ensure_engine_binaries(lambda line: print(line))
    )
    local_universe.start(spec)
    env = {
        **os.environ,
        PG_DSN_ENV: local_universe.local_dsn(spec),
        ADMIN_NAME_ENV: OWNER_NAME,
        API_PUBLISH_ENV: f"127.0.0.1:{MODE_PORTS[mode]}",
        # The self-host bundle declares its mode the same way.
        SERVER_MODE_ENV: SERVER_MODE_SELF_HOST,
    }
    provider = (
        _company_sign_in(mode, env) if mode == "self-hosted-company-sign-in" else None
    )
    token_path = approver / "owner.token"
    host_end, server_end = socket.socketpair()
    env[FIRST_BOOT_TOKEN_FD_ENV] = str(server_end.fileno())
    env[FIRST_BOOT_TOKEN_HOST_PATH_ENV] = str(token_path)
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "yoke_core.api.server_entrypoint",
            "--host",
            "127.0.0.1",
            "--port",
            str(MODE_PORTS[mode]),
        ],
        env=env,
        pass_fds=(server_end.fileno(),),
        stdin=subprocess.DEVNULL,
    )
    server_end.close()
    signal.signal(signal.SIGTERM, lambda *_args: child.terminate())
    try:
        receive_owner_token(host_end, token_path)
        # This supervisor is the approver's machine; the server child already
        # holds its own environment.
        os.environ[MACHINE_HOME_ENV] = str(approver)
        try:
            writer.set_connection(
                APPROVER_ENV,
                transport="https",
                api_url=api_url(mode),
                token_file=str(token_path),
                prod=False,
                activate=True,
            )
        except writer.MachineConfigWriteError as exc:
            raise AdmissionFixtureError(
                f"machine_admission_approver_config_failed: {exc}; repair the "
                "fixture root's permissions on the test machine, then rerun."
            ) from exc
        if provider is not None:
            # The token arrives during birth, before the server listens.
            while server_methods(mode) is None:
                if child.poll() is not None:
                    return child.returncode
                time.sleep(0.5)
            invite_teammate_identity()
        write_private(mode_root(mode) / "ready", "ready\n")
        return child.wait()
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=30)
        host_end.close()
        if provider is not None:
            provider.close()
        local_universe.stop(spec)


__all__ = ["receive_owner_token", "run_server"]
