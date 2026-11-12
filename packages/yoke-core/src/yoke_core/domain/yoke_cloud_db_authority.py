"""Helpers for resolving Yoke cloud Postgres authority.

This module is intentionally small: it converts declared stack/output facts
and a Secrets Manager JSON payload into a libpq DSN. Every Pulumi and AWS child
runs with a caller-supplied environment carrying the project's aws-admin
capability credentials, never the operator's ambient AWS login, and every
failure surfaces the child's redacted stderr as a named
:class:`CloudAuthorityCommandError`.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


DEFAULT_ENDPOINT_OUTPUT = "databaseClusterEndpoint"
DEFAULT_SECRET_ARN_OUTPUT = "databaseSecretArn"
DEFAULT_POSTGRES_PORT = 5432
CLI_TIMEOUT_SECONDS = 120
_STDERR_TAIL_CHARS = 1200


class CloudAuthorityCommandError(RuntimeError):
    """A Pulumi or AWS child command failed; carries its redacted cause."""

    def __init__(self, step: str, detail: str, recovery: str) -> None:
        super().__init__(f"{step} failed: {detail}; {recovery}")
        self.step = step
        self.detail = detail
        self.recovery = recovery


def failure_cause(exc: BaseException) -> str:
    """Name a failure safely: a refusal's redacted detail, else only its class.

    Other loader errors may carry secret material in their text.
    """
    if isinstance(exc, CloudAuthorityCommandError):
        return exc.detail
    return type(exc).__name__


@dataclass(frozen=True)
class PostgresAuthorityLocation:
    stack: str
    database_name: str
    endpoint_output: str = DEFAULT_ENDPOINT_OUTPUT
    secret_arn_output: str = DEFAULT_SECRET_ARN_OUTPUT
    state_backend: Optional[str] = None
    region: Optional[str] = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PostgresAuthorityLocation":
        if not isinstance(value.get("stack"), str) or not value["stack"]:
            raise CloudAuthorityCommandError(
                "cloud_postgres_location",
                "stack must be a non-empty string for cloud Postgres authority",
                "declare authoritative_db.location.stack for the Aurora model; "
                "for box Postgres use db-admin setup with an environment whose "
                "database.location is box",
            )
        return cls(
            stack=_required_str(value, "stack"),
            database_name=_required_str(value, "database_name"),
            endpoint_output=str(
                value.get("endpoint_output") or DEFAULT_ENDPOINT_OUTPUT
            ),
            secret_arn_output=str(
                value.get("secret_arn_output") or DEFAULT_SECRET_ARN_OUTPUT
            ),
            state_backend=_optional_str(value, "state_backend"),
            region=_optional_str(value, "region"),
        )

    def as_settings_location(self) -> dict:
        out = {
            "stack": self.stack,
            "database_name": self.database_name,
            "endpoint_output": self.endpoint_output,
            "secret_arn_output": self.secret_arn_output,
        }
        if self.state_backend:
            out["state_backend"] = self.state_backend
        if self.region:
            out["region"] = self.region
        return out


@dataclass(frozen=True)
class PostgresSecret:
    username: str
    password: str
    engine: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None

    @classmethod
    def from_json(cls, raw: str) -> "PostgresSecret":
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"database secret is not JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("database secret JSON must be an object")
        return cls(
            username=_required_str(payload, "username"),
            password=_required_str(payload, "password"),
            engine=_optional_str(payload, "engine"),
            host=_optional_str(payload, "host"),
            port=_optional_int(payload, "port"),
        )


def load_stack_outputs(
    infra_dir: Path,
    location: PostgresAuthorityLocation,
    *,
    env: Mapping[str, str],
) -> Mapping[str, Any]:
    """Read Pulumi stack outputs as JSON without exposing secrets.

    ``env`` carries the capability-owned AWS credentials the state backend and
    stack read authenticate with; there is no ambient-credential default.
    """
    recovery = (
        f"check stack {location.stack!r} exists in {infra_dir} and that the "
        "project's aws-admin capability can reach its state backend"
    )
    if location.state_backend:
        _run_cli(
            ["pulumi", "login", location.state_backend],
            step=f"pulumi login {location.state_backend}",
            recovery=recovery,
            env=env,
            cwd=infra_dir,
        )
    stdout = _run_cli(
        ["pulumi", "stack", "output", "--stack", location.stack, "--json"],
        step=f"pulumi stack output --stack {location.stack}",
        recovery=recovery,
        env=env,
        cwd=infra_dir,
    )
    parsed = json.loads(stdout or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("Pulumi stack output JSON must be an object")
    return parsed


def load_secret_string(
    secret_arn: str,
    *,
    env: Mapping[str, str],
    region: Optional[str] = None,
    version_stage: Optional[str] = None,
) -> str:
    """Read a secret's JSON string from AWS Secrets Manager.

    ``env`` carries the capability-owned AWS credentials; there is no
    ambient-credential default.
    """
    cmd = [
        "aws",
        "secretsmanager",
        "get-secret-value",
        "--secret-id",
        secret_arn,
        "--query",
        "SecretString",
        "--output",
        "text",
    ]
    if region:
        cmd.extend(["--region", region])
    if version_stage:
        cmd.extend(["--version-stage", version_stage])
    stdout = _run_cli(
        cmd,
        step=f"aws secretsmanager get-secret-value {secret_arn}",
        recovery=(
            "rerun once AWS is reachable; if it persists, confirm the project's "
            "aws-admin capability may read the secret with `yoke aws exec "
            f"-- secretsmanager describe-secret --secret-id {secret_arn}`"
        ),
        env=env,
    )
    return stdout.strip()


def _run_cli(
    argv: list[str],
    *,
    step: str,
    recovery: str,
    env: Mapping[str, str],
    cwd: Optional[Path] = None,
) -> str:
    """Run one child command; refuse with its redacted stderr on failure."""
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            env=dict(env),
            timeout=CLI_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise CloudAuthorityCommandError(
            step,
            f"`{argv[0]}` is not installed or not on PATH",
            f"install `{argv[0]}` on this machine and rerun",
        ) from None
    except subprocess.TimeoutExpired:
        raise CloudAuthorityCommandError(
            step,
            f"no answer within {CLI_TIMEOUT_SECONDS}s",
            "check network reachability to AWS and rerun",
        ) from None
    if proc.returncode != 0:
        from yoke_core.domain.connected_env_readiness_connector import redact

        stderr = (proc.stderr or "").strip()[-_STDERR_TAIL_CHARS:]
        detail = f"exit {proc.returncode}: {redact(stderr) or 'no stderr output'}"
        raise CloudAuthorityCommandError(step, detail, recovery)
    return proc.stdout or ""


def endpoint_and_secret_arn(
    outputs: Mapping[str, Any],
    location: PostgresAuthorityLocation,
) -> tuple[str, str]:
    endpoint = _required_str(outputs, location.endpoint_output)
    secret_arn = _required_str(outputs, location.secret_arn_output)
    return endpoint, secret_arn


def build_libpq_dsn(
    *,
    host: str,
    database: str,
    secret: PostgresSecret,
    port: int = DEFAULT_POSTGRES_PORT,
) -> str:
    """Build a libpq key/value DSN, safely quoting user-controlled values."""
    parts = {
        "host": host,
        "port": str(port),
        "user": secret.username,
        "password": secret.password,
        "dbname": database,
    }
    return " ".join(f"{key}={shlex.quote(value)}" for key, value in parts.items())


def redacted_dsn(dsn: str) -> str:
    parts = []
    for token in shlex.split(dsn):
        if token.startswith("password="):
            parts.append("password=<redacted>")
        else:
            parts.append(token)
    return " ".join(parts)


def resolve_declared_dsn(
    *,
    infra_dir: Path,
    location: PostgresAuthorityLocation,
    aws_env: Mapping[str, str],
    host_override: Optional[str] = None,
    port_override: Optional[int] = None,
) -> tuple[str, dict]:
    """Resolve DSN plus redacted evidence from Pulumi outputs + AWS secret.

    ``aws_env`` is the aws-admin capability environment both reads run under.
    """
    outputs = load_stack_outputs(infra_dir, location, env=aws_env)
    endpoint, secret_arn = endpoint_and_secret_arn(outputs, location)
    secret = PostgresSecret.from_json(
        load_secret_string(secret_arn, region=location.region, env=aws_env)
    )
    host = host_override or endpoint
    port = port_override or secret.port or DEFAULT_POSTGRES_PORT
    dsn = build_libpq_dsn(
        host=host,
        port=port,
        database=location.database_name,
        secret=secret,
    )
    return dsn, {
        "stack": location.stack,
        "endpoint_output": location.endpoint_output,
        "secret_arn_output": location.secret_arn_output,
        "endpoint": endpoint,
        "database_name": location.database_name,
        "dsn": redacted_dsn(dsn),
    }


def _required_str(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_str(mapping: Mapping[str, Any], key: str) -> Optional[str]:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string when present")
    return value


def _optional_int(mapping: Mapping[str, Any], key: str) -> Optional[int]:
    value = mapping.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer when present") from exc
