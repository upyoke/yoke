"""environment-bootstrap executor — initialize a deploy env's empty Yoke DB.

Takes one project environment from an applied Pulumi stack to a complete,
empty-but-fully-shaped Yoke control-plane database:

1. resolve the environment + capabilities (:mod:`deploy_environment_settings`),
   refusing ``render_only`` declarations (apply the stack first);
2. ensure the env origin is running and SSH-reachable (reusing the
   environment-activate helpers);
3. resolve the env's Postgres DSN from Pulumi stack outputs + the
   RDS-managed master secret (reusing the core-deploy resolver);
4. open a local SSH port-forward through the origin — the env database is
   VPC-internal (``publicly_accessible=False``), so laptop-side bootstrap
   reaches it the same way the prod connected-env does;
5. run the complete init chain + event-registry population
   (:mod:`environment_bootstrap`) in a DSN-pinned subprocess so the parent
   process never rebinds its own control-plane authority;
6. tear the tunnel down and emit ``DeploymentEnvironmentBootstrapped``.

Policy: this is the ONLY sanctioned way a stage/ephemeral/self-host env DB
reaches the Yoke schema. It is idempotent — re-running refreshes a
throwaway env's schema to the deployed code's expectations. The governed
migration path applies exclusively to a project's declared authoritative
DB (prod); stage/ephemeral data never promotes and is never migrated.

CLI::

    python3 -m yoke_core.domain.deploy_environment_bootstrap <project> <env>

Secrets only travel via the subprocess env mapping; no emitted line ever
carries the DSN.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Callable, Optional

from yoke_core.domain.deploy_core_container import (
    CoreDeployError,
    resolve_environment_dsn,
)
from yoke_core.domain.deploy_environment_activate import (
    EnvironmentActivateError,
    ensure_instance_running,
    wait_ssh_reachable,
)
from yoke_core.domain.deploy_environment_settings import (
    DeployEnvironmentError,
    resolve_deploy_environment,
)
from yoke_core.domain.deploy_remote import (
    CommandRunner,
    aws_capability_env,
    close_db_tunnel,
    db_tunnel_forward_spec,
    free_local_port,
    open_db_tunnel,
)

_BOOTSTRAP_TIMEOUT_S = 900
_ENDPOINT_OUTPUT = "databaseClusterEndpoint"


class EnvironmentBootstrapError(RuntimeError):
    """Environment DB bootstrap failed; message carries remediation."""


def _emit(line: str) -> None:
    print(line, flush=True)


def _dsn_port(dsn: str) -> int:
    match = re.search(r"(?:^|\s)port=(\d+)", dsn)
    return int(match.group(1)) if match else 5432


def _localize_dsn(dsn: str, local_port: int) -> str:
    """Point the DSN at the local forward.

    ``build_libpq_dsn`` emits ``host=`` then ``port=`` ahead of the
    credential keys, so first-occurrence substitution rewrites exactly the
    connection tokens and never quoted credential content.
    """
    dsn = re.sub(r"(^|\s)host=\S+", r"\1host=127.0.0.1", dsn, count=1)
    return re.sub(r"(^|\s)port=\d+", rf"\1port={local_port}", dsn, count=1)


def _subprocess_env(dsn: str) -> dict:
    """Build the DSN-pinned bootstrap subprocess environment.

    Pins ``YOKE_PG_DSN`` to the target env's authority and opts the
    process into explicit bootstrap (``YOKE_DB_INIT_ALLOW``). Drops any
    inherited DSN-file/init-done markers so nothing short-circuits or
    rebinds the child's authority resolution.
    """
    env = dict(os.environ)
    env.pop("YOKE_PG_DSN_FILE", None)
    env.pop("YOKE_DB_INIT_DONE", None)
    env["YOKE_PG_DSN"] = dsn
    env["YOKE_DB_INIT_ALLOW"] = "1"
    return env


def exec_environment_bootstrap(
    project: str,
    env_name: str,
    *,
    runner: Optional[CommandRunner] = None,
    emit: Callable[[str], None] = _emit,
) -> int:
    """Bootstrap ``project``/``env_name``'s empty DB to the complete shape."""
    runner = runner or CommandRunner()
    try:
        env = resolve_deploy_environment(project, env_name)
        if env.activation_state == "render_only":
            raise EnvironmentBootstrapError(
                f"[env-bootstrap] environment '{env_name}' of project "
                f"'{project}' is declared render_only; apply its Pulumi "
                f"stack ({env.stack_name}) and set "
                "environments.settings.pulumi.activation_state='active' "
                "(python3 -m yoke_core.domain.projects "
                "environment-merge-settings <env-id> "
                "--set pulumi.activation_state=active) before bootstrapping"
            )
        emit(
            f"  [env-bootstrap] target {env.project}/{env.env_name} "
            f"(database {env.database_name}, stack {env.stack_name})"
        )

        aws_env = aws_capability_env(env.project, env.aws_region)
        ensure_instance_running(runner, env, aws_env, emit)
        wait_ssh_reachable(runner, env, emit)
        dsn, outputs = resolve_environment_dsn(runner, env, aws_env, emit=emit)

        endpoint = str(outputs.get(_ENDPOINT_OUTPUT) or "")
        if not endpoint:
            raise EnvironmentBootstrapError(
                f"[env-bootstrap] stack {env.stack_name} outputs are "
                f"missing '{_ENDPOINT_OUTPUT}'; apply the environment stack"
            )
        local_port = free_local_port()
        forward = db_tunnel_forward_spec(local_port, endpoint, _dsn_port(dsn))
        emit(
            f"  [env-bootstrap] opening db tunnel through "
            f"{env.origin_host} (local port {local_port})"
        )
        try:
            open_db_tunnel(runner, env, forward)
        except RuntimeError as exc:
            raise EnvironmentBootstrapError(f"[env-bootstrap] {exc}") from exc

        try:
            result = runner.run(
                [
                    sys.executable, "-m",
                    "yoke_core.domain.environment_bootstrap",
                ],
                env=_subprocess_env(_localize_dsn(dsn, local_port)),
                timeout=_BOOTSTRAP_TIMEOUT_S,
            )
        finally:
            close_db_tunnel(runner, forward)
        for line in (result.stdout or "").splitlines():
            emit(f"  {line}")
        if not result.ok:
            raise EnvironmentBootstrapError(
                "[env-bootstrap] bootstrap subprocess failed "
                f"(exit {result.returncode}): "
                + (result.stderr or result.stdout).strip()[-800:]
            )

        _emit_bootstrap_event(env)
        emit(
            f"  [env-bootstrap] {env.project}/{env.env_name} database "
            f"'{env.database_name}' bootstrapped to the complete "
            "control-plane shape"
        )
        return 0
    except (
        EnvironmentBootstrapError,
        EnvironmentActivateError,
        DeployEnvironmentError,
        CoreDeployError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


def _emit_bootstrap_event(env) -> None:
    """Record the bootstrap through the canonical emitter (best-effort)."""
    try:
        from yoke_core.domain.events import emit_event

        emit_event(
            "DeploymentEnvironmentBootstrapped",
            event_kind="lifecycle",
            event_type="deployment_run",
            source_type="system",
            severity="STATUS",
            project=env.project,
            outcome="completed",
            environment=env.env_name,
            context={
                "database_name": env.database_name,
                "stack_name": env.stack_name,
            },
        )
    except Exception as exc:  # pragma: no cover - telemetry is best-effort
        print(
            f"  [env-bootstrap] warning: bootstrap event emission "
            f"failed: {exc}",
            file=sys.stderr,
        )


def main(argv: Optional[list] = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print(
            "Usage: python3 -m yoke_core.domain."
            "deploy_environment_bootstrap <project> <env>\n"
            "Bootstraps the named deploy environment's empty Postgres "
            "database\nto the complete Yoke control-plane shape "
            "(init chain + event\nregistry), resolving the DSN from Pulumi "
            "stack outputs + the\nRDS-managed secret and tunnelling "
            "through the env origin.",
            file=sys.stderr,
        )
        return 2
    return exec_environment_bootstrap(args[0], args[1])


if __name__ == "__main__":
    sys.exit(main())
