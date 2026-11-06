"""Remote-execution plumbing for deployment-flow step runners.

Owns three concerns shared by the core-container deploy and
environment-activate step runners:

- a :class:`CommandRunner` seam so tests assert the exact command plan
  without touching subprocess, SSH, Docker, or AWS;
- ``ssh``/argv builders bound to a :class:`DeployEnvironment`'s declared
  ssh capability (key path, user, origin host);
- AWS credential materialization from a selected project capability
  (``aws-admin`` by default) into a subprocess environment (never printed,
  never written to disk), per the capability-owned-credentials rule.

Secret-bearing values only ever travel through ``input=`` stdin payloads
or subprocess ``env`` mappings. Nothing here logs argv containing a
secret; callers that need evidence log redacted forms.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import List, Mapping, Optional, Sequence

from yoke_core.domain import json_helper
from yoke_contracts.machine_config import capability_secret_store as capability_machine_secrets
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote_atomic_file import (
    push_remote_file as push_remote_file,
    remove_remote_file as remove_remote_file,
)
from yoke_core.domain.projects_capabilities import cmd_capability_get_secret
from yoke_core.domain.projects_capabilities_settings import (
    cmd_capability_get_settings,
)

_SSH_BASE_OPTIONS: Sequence[str] = (
    "-o",
    "BatchMode=yes",
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    "ConnectTimeout=10",
)
AWS_AMBIENT_AUTH_ENV_VARS: Sequence[str] = (
    "AWS_CONFIG_FILE",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_DEFAULT_PROFILE",
    "AWS_PROFILE",
    "AWS_ROLE_ARN",
    "AWS_ROLE_SESSION_NAME",
    "AWS_SECURITY_TOKEN",
    "AWS_SESSION_TOKEN",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
)
DEFAULT_AWS_CAPABILITY_TYPE = "aws-admin"


@dataclass
class CommandResult:
    """Subprocess outcome the step runners branch on."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandRunner:
    """Default runner: subprocess with captured text output."""

    def run(
        self,
        argv: Sequence[str],
        *,
        input_text: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        timeout: int = 600,
    ) -> CommandResult:
        completed = subprocess.run(
            list(argv),
            input=input_text,
            env=dict(env) if env is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


def aws_capability_region(
    project: str,
    *,
    capability_type: str = DEFAULT_AWS_CAPABILITY_TYPE,
) -> str | None:
    """Return the selected AWS capability's region, if configured."""
    settings_text = cmd_capability_get_settings(project, capability_type)
    if not settings_text:
        return None
    parsed = json_helper.loads_text(settings_text)
    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"project '{project}' {capability_type} capability settings "
            "must be a JSON object"
        )
    region = str(parsed.get("region") or "").strip()
    return region or None


def aws_capability_env(
    project: str,
    region: str,
    *,
    capability_type: str = DEFAULT_AWS_CAPABILITY_TYPE,
) -> dict[str, str]:
    """Materialize selected AWS capability credentials into a child env.

    Returns a copy of ``os.environ`` extended with the capability-owned
    access key pair and default region so ``aws``/``pulumi``/``docker``
    subprocesses authenticate without exporting anything into the
    operator shell. Outside GitHub Actions (whose OIDC role is the declared
    authority) missing capability creds refuse; the operator's ambient AWS
    login is never a fallback.
    """
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true":
        return _materialize_aws_env(
            project=project,
            region=region,
            capability_type=capability_type,
            access_key=None,
            secret_key=None,
            session_token=None,
        )
    access_key = cmd_capability_get_secret(project, capability_type, "access_key_id")
    secret_key = cmd_capability_get_secret(
        project, capability_type, "secret_access_key"
    )
    session_token = cmd_capability_get_secret(project, capability_type, "session_token")
    return _materialize_aws_env(
        project=project,
        region=region,
        capability_type=capability_type,
        access_key=access_key,
        secret_key=secret_key,
        session_token=session_token,
    )


def aws_machine_capability_env(
    project_slug: str,
    region: str,
    *,
    capability_type: str = DEFAULT_AWS_CAPABILITY_TYPE,
) -> dict[str, str]:
    """Materialize AWS credentials directly from the machine-local store.

    Unlike :func:`aws_capability_env`, this recovery surface never opens the
    selected Yoke database merely to resolve a project slug. The caller must
    therefore provide the canonical slug already recorded in machine config.
    """

    project = str(project_slug or "").strip()
    if not project:
        raise RuntimeError("project slug is required for machine AWS authority")
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true":
        return _materialize_aws_env(
            project=project,
            region=region,
            capability_type=capability_type,
            access_key=None,
            secret_key=None,
            session_token=None,
        )
    access_key = capability_machine_secrets.read_machine_capability_secret(
        project, capability_type, "access_key_id"
    )
    secret_key = capability_machine_secrets.read_machine_capability_secret(
        project, capability_type, "secret_access_key"
    )
    session_token = capability_machine_secrets.read_machine_capability_secret(
        project, capability_type, "session_token"
    )
    return _materialize_aws_env(
        project=project,
        region=region,
        capability_type=capability_type,
        access_key=access_key,
        secret_key=secret_key,
        session_token=session_token,
    )


def _materialize_aws_env(
    *,
    project: str,
    region: str,
    capability_type: str,
    access_key: str | None,
    secret_key: str | None,
    session_token: str | None,
) -> dict[str, str]:
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true":
        if not os.environ.get("AWS_ACCESS_KEY_ID", "").strip() or not (
            os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
        ):
            raise RuntimeError(
                "GitHub Actions selected ambient OIDC authority, but "
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are absent; "
                "run aws-actions/configure-aws-credentials first"
            )
        env = dict(os.environ)
        env["AWS_DEFAULT_REGION"] = region
        env["AWS_REGION"] = region
        env["AWS_PAGER"] = ""
        return env

    if not access_key or not secret_key:
        raise RuntimeError(
            f"project '{project}' {capability_type} capability secrets are "
            "missing (need access_key_id + secret_access_key); Yoke never "
            "falls back to the ambient AWS login. Store them on this machine "
            "via `yoke projects capability secret set --project "
            f"{project} --cap-type {capability_type} "
            "--key access_key_id VALUE` "
            "and `--key secret_access_key VALUE`"
        )
    env = dict(os.environ)
    for name in AWS_AMBIENT_AUTH_ENV_VARS:
        env.pop(name, None)
    # Detach the shared ~/.aws files the CLI and SDKs read by default.
    env["AWS_CONFIG_FILE"] = os.devnull
    env["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
    env["AWS_ACCESS_KEY_ID"] = access_key.strip()
    env["AWS_SECRET_ACCESS_KEY"] = secret_key.strip()
    env["AWS_DEFAULT_REGION"] = region
    env["AWS_REGION"] = region
    env["AWS_PAGER"] = ""
    if session_token:
        env["AWS_SESSION_TOKEN"] = session_token.strip()
    return env


def ssh_argv(
    env: DeployEnvironment,
    remote_command: str,
    *,
    connect_timeout: Optional[int] = None,
) -> List[str]:
    """Build the ``ssh`` argv for one remote command on the env origin."""
    options = list(_SSH_BASE_OPTIONS)
    if connect_timeout is not None:
        options[options.index("ConnectTimeout=10")] = (
            f"ConnectTimeout={connect_timeout}"
        )
    return [
        "ssh",
        "-i",
        env.ssh_key_path,
        *options,
        env.ssh_target,
        remote_command,
    ]


def run_remote(
    runner: CommandRunner,
    env: DeployEnvironment,
    remote_command: str,
    *,
    input_text: Optional[str] = None,
    timeout: int = 600,
) -> CommandResult:
    """Run one remote command over SSH on the environment origin host."""
    return runner.run(
        ssh_argv(env, remote_command),
        input_text=input_text,
        timeout=timeout,
    )


def free_local_port() -> int:
    """Bind an ephemeral port to learn a free local port number."""
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def db_tunnel_forward_spec(local_port: int, db_host: str, db_port: int) -> str:
    """The ``-L`` forward spec for a local->env-database tunnel."""
    return f"127.0.0.1:{local_port}:{db_host}:{db_port}"


def open_db_tunnel(
    runner: CommandRunner,
    env: DeployEnvironment,
    forward_spec: str,
    *,
    timeout: int = 30,
) -> None:
    """Open a backgrounded SSH port-forward through the env origin.

    The env's database is VPC-internal (``publicly_accessible=False``), so
    laptop-side operations reach it exactly the way the prod connected-env
    does: a local forward through the origin box. ``ExitOnForwardFailure``
    makes a failed bind a loud nonzero exit instead of a silent dead port.
    """
    argv = [
        "ssh",
        "-i",
        env.ssh_key_path,
        *_SSH_BASE_OPTIONS,
        "-o",
        "ExitOnForwardFailure=yes",
        "-N",
        "-f",
        "-L",
        forward_spec,
        env.ssh_target,
    ]
    result = runner.run(argv, timeout=timeout)
    if not result.ok:
        raise RuntimeError(
            f"db tunnel open failed (rc={result.returncode}): "
            + (result.stderr or result.stdout).strip()[-400:]
        )


def close_db_tunnel(
    runner: CommandRunner, forward_spec: str, *, timeout: int = 10
) -> None:
    """Terminate the backgrounded forward matching *forward_spec*.

    Best-effort: rc=1 (no match) is fine — the forward may have exited.
    """
    runner.run(["pkill", "-f", "--", f"-L {forward_spec}"], timeout=timeout)
