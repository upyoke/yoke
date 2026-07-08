"""Host-box convergence steps for the ephemeral-deploy executor.

Each function converges one aspect of the preview substrate on the host
environment's origin box over SSH and is idempotent: probe first, mutate
only when the probe fails, verify after. The orchestrator
(:mod:`yoke_core.domain.deploy_ephemeral`) sequences these.

The host box is the same origin the persistent env's core service runs
on; previews share its compute and nginx while staying isolated per slug
(own compose project, own Postgres sidecar, own localhost port).
"""

from __future__ import annotations

import uuid
from typing import Callable

from yoke_core.domain.deploy_core_container_remote import (
    RemoteConvergenceError,
    _fail,
)
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import (
    CommandRunner,
    push_remote_file,
    run_remote,
)

_APT_INSTALL = (
    "sudo env DEBIAN_FRONTEND=noninteractive apt-get update -q"
    " && sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q "
)
_NJS_PACKAGE_PROBE = "dpkg -s libnginx-mod-http-js >/dev/null 2>&1"
_CERTBOT_PROBE = (
    "command -v certbot >/dev/null 2>&1"
    " && dpkg -s python3-certbot-dns-route53 >/dev/null 2>&1"
)


def _push_or_fail(
    runner, env, *, content: str, remote_path: str, mode: str, sudo: bool,
    step: str, secret: bool = False,
) -> None:
    push = push_remote_file(
        runner, env, content=content, remote_path=remote_path, mode=mode,
        sudo=sudo,
    )
    if push.ok:
        return
    if secret:
        # Secret-bearing payloads — never include them in the failure.
        raise RemoteConvergenceError(
            f"[ephemeral] {step} write failed (rc={push.returncode})"
        )
    _fail(step, push)


def ensure_wildcard_tls(
    runner: CommandRunner,
    env: DeployEnvironment,
    preview_domain: str,
    emit: Callable[[str], None],
) -> None:
    """Issue the ``*.{preview_domain}`` Let's Encrypt cert when absent.

    DNS-01 via certbot-dns-route53 using the origin instance profile (the
    environment stack grants the zone-scoped Route 53 permissions when the
    preview domain is declared). Renewal rides certbot's system timer with
    the same instance credentials; the deploy hook reloads nginx.
    """
    cert_path = f"/etc/letsencrypt/live/{preview_domain}/fullchain.pem"
    probe = run_remote(runner, env, f"sudo test -s {cert_path}", timeout=30)
    if probe.ok:
        emit(f"  [ephemeral] wildcard TLS present for *.{preview_domain}")
        return

    packages = run_remote(runner, env, _CERTBOT_PROBE, timeout=30)
    if not packages.ok:
        emit("  [ephemeral] installing certbot + dns-route53 plugin")
        install = run_remote(
            runner, env,
            _APT_INSTALL + "certbot python3-certbot-dns-route53",
            timeout=600,
        )
        if not install.ok:
            _fail("certbot install", install)

    emit(f"  [ephemeral] issuing wildcard cert for *.{preview_domain}")
    issue = run_remote(
        runner,
        env,
        "sudo certbot certonly --dns-route53"
        f' -d "*.{preview_domain}"'
        f" --cert-name {preview_domain}"
        " --non-interactive --agree-tos --register-unsafely-without-email"
        ' --deploy-hook "systemctl reload nginx"',
        timeout=600,
    )
    if not issue.ok:
        _fail(
            "wildcard cert issuance",
            issue,
            remediation=(
                "DNS-01 needs the origin role's Route 53 grants; apply the "
                f"environment stack ({env.stack_name}) with the ephemeral "
                "preview domain declared"
            ),
        )
    emit(f"  [ephemeral] wildcard TLS issued for *.{preview_domain}")


def ensure_preview_routing(
    runner: CommandRunner,
    env: DeployEnvironment,
    nginx_site: str,
    njs_script: str,
    emit: Callable[[str], None],
) -> None:
    """Install the njs module, port-computation script, and wildcard site."""
    probe = run_remote(runner, env, _NJS_PACKAGE_PROBE, timeout=30)
    if not probe.ok:
        emit("  [ephemeral] installing nginx njs module")
        install = run_remote(
            runner, env, _APT_INSTALL + "libnginx-mod-http-js", timeout=600
        )
        if not install.ok:
            _fail("nginx njs module install", install)

    mkdir = run_remote(
        runner, env, "sudo mkdir -p /etc/nginx/njs.d", timeout=30
    )
    if not mkdir.ok:
        _fail("njs script dir creation", mkdir)
    _push_or_fail(
        runner, env, content=njs_script,
        remote_path="/etc/nginx/njs.d/ephemeral_port.js", mode="644",
        sudo=True, step="njs port script",
    )
    site_name = f"{env.deploy_namespace}-ephemeral"
    _push_or_fail(
        runner, env, content=nginx_site,
        remote_path=f"/etc/nginx/sites-available/{site_name}", mode="644",
        sudo=True, step="ephemeral nginx site",
    )
    activate = run_remote(
        runner,
        env,
        f"sudo ln -sf /etc/nginx/sites-available/{site_name}"
        f" /etc/nginx/sites-enabled/{site_name}"
        " && sudo nginx -t && sudo systemctl reload nginx",
        timeout=60,
    )
    if not activate.ok:
        _fail("ephemeral nginx site activation", activate)
    emit("  [ephemeral] wildcard preview routing converged")


def ensure_cleanup_cron(
    runner: CommandRunner,
    env: DeployEnvironment,
    cleanup_script: str,
    emit: Callable[[str], None],
) -> None:
    """Install the rendered TTL cleanup script + its cron schedule."""
    script_path = f"/usr/local/bin/{env.deploy_namespace}-ephemeral-cleanup"
    _push_or_fail(
        runner, env, content=cleanup_script, remote_path=script_path,
        mode="755", sudo=True, step="ephemeral cleanup script",
    )
    cron_line = (
        f"0 */6 * * * {env.ssh_user} sh {script_path}"
        f" >> /tmp/{env.deploy_namespace}-ephemeral-cleanup.log 2>&1\n"
    )
    _push_or_fail(
        runner, env, content=cron_line,
        remote_path=f"/etc/cron.d/{env.deploy_namespace}-ephemeral-cleanup",
        mode="644", sudo=True, step="ephemeral cleanup cron",
    )
    emit("  [ephemeral] TTL cleanup cron converged")


def read_existing_db_password(
    runner: CommandRunner, env: DeployEnvironment, deploy_dir: str
) -> str:
    """Return the slug's existing DB password, or empty when first deploy.

    The disposable Postgres applies its password only at initdb, so a
    redeploy must reuse the secret stored beside the compose project
    rather than minting a new one the volume would ignore.
    """
    probe = run_remote(
        runner, env, f"cat {deploy_dir}/db-password 2>/dev/null", timeout=30
    )
    value = probe.stdout.strip() if probe.ok else ""
    return value if value and all(c in "0123456789abcdef" for c in value) else ""


def generate_db_password() -> str:
    """Hex-only secret: safe through compose env-file interpolation."""
    return uuid.uuid4().hex


def converge_slug_project(
    runner: CommandRunner,
    env: DeployEnvironment,
    deploy_dir: str,
    compose_yaml: str,
    env_file: str,
    dsn: str,
    db_password: str,
    emit: Callable[[str], None],
) -> None:
    """Materialize the per-slug compose dir + compose/env/dsn/secret files."""
    prepare = run_remote(
        runner,
        env,
        f"mkdir -p {deploy_dir} && chmod 700 {deploy_dir}",
        timeout=30,
    )
    if not prepare.ok:
        _fail("slug deploy dir preparation", prepare)

    _push_or_fail(
        runner, env, content=compose_yaml,
        remote_path=f"{deploy_dir}/docker-compose.yml", mode="644",
        sudo=False, step="slug compose file",
    )
    for content, name, mode in (
        (db_password + "\n", "db-password", "600"),
        (env_file, ".env", "600"),
        # 444 file in 700 dir: container reads it at any uid; host can't.
        (dsn + "\n", "dsn", "444"),
    ):
        _push_or_fail(
            runner, env, content=content,
            remote_path=f"{deploy_dir}/{name}", mode=mode, sudo=False,
            step=f"slug {name} file", secret=True,
        )
    emit("  [ephemeral] slug compose project converged")


def compose_bootstrap_and_up(
    runner: CommandRunner,
    env: DeployEnvironment,
    deploy_dir: str,
    emit: Callable[[str], None],
) -> None:
    """Pull, bootstrap the disposable DB in-container, start the service.

    The bootstrap runs the *deployed image's own code*
    (``yoke_core.domain.environment_bootstrap``) so the preview schema
    always matches the deployed branch — never the orchestrating
    checkout's. ``docker compose run`` starts the db dependency and waits
    for its healthcheck before the one-shot bootstrap container runs.
    """
    emit("  [ephemeral] docker compose pull")
    pull = run_remote(
        runner,
        env,
        f"cd {deploy_dir} && docker compose pull --quiet",
        timeout=900,
    )
    if not pull.ok:
        _fail("ephemeral compose pull", pull)

    emit("  [ephemeral] bootstrapping disposable DB (in-container)")
    bootstrap = run_remote(
        runner,
        env,
        f"cd {deploy_dir} && docker compose run --rm"
        " -e YOKE_DB_INIT_ALLOW=1 core"
        " python -m yoke_core.domain.environment_bootstrap",
        timeout=900,
    )
    if not bootstrap.ok:
        _fail("ephemeral DB bootstrap", bootstrap)
    for line in bootstrap.stdout.splitlines():
        if "verified:" in line or "bootstrap complete" in line:
            emit(f"  {line.strip()}")

    emit("  [ephemeral] docker compose up -d")
    # --force-recreate: a stale container keeps the re-inoded dsn mount.
    up = run_remote(
        runner,
        env,
        f"cd {deploy_dir} && docker compose up -d"
        " --remove-orphans --force-recreate",
        timeout=300,
    )
    if not up.ok:
        _fail("ephemeral compose up", up)


def verify_slug_health(
    runner: CommandRunner,
    env: DeployEnvironment,
    api_port: int,
    health_path: str,
    request_id: str,
    emit: Callable[[str], None],
) -> None:
    """Hit the slug's localhost port on the box, asserting request-id echo."""
    check = run_remote(
        runner,
        env,
        f'curl -fsS -m 15 -D - -o /dev/null -H "x-request-id: {request_id}" '
        f"http://127.0.0.1:{api_port}{health_path}",
        timeout=30,
    )
    if not check.ok:
        _fail("slug health check", check)
    if f"x-request-id: {request_id}".lower() not in check.stdout.lower():
        raise RemoteConvergenceError(
            "[ephemeral] slug health response did not echo x-request-id "
            f"'{request_id}'; request-id propagation is part of the deploy "
            "contract"
        )
    emit(
        f"  [ephemeral] slug health ok on port {api_port} "
        f"(request-id {request_id} echoed)"
    )


def teardown_slug_project(
    runner: CommandRunner,
    env: DeployEnvironment,
    deploy_dir: str,
    compose_project: str,
    emit: Callable[[str], None],
) -> None:
    """Compose down with volumes, then remove the slug deploy directory."""
    down = run_remote(
        runner,
        env,
        f"cd {deploy_dir} 2>/dev/null"
        " && docker compose down --volumes --remove-orphans"
        f" || docker compose -p {compose_project} down --volumes"
        " --remove-orphans || true",
        timeout=300,
    )
    if not down.ok:
        _fail("ephemeral compose down", down)
    cleanup = run_remote(runner, env, f"rm -rf {deploy_dir}", timeout=60)
    if not cleanup.ok:
        _fail("slug deploy dir removal", cleanup)
    emit(f"  [ephemeral] {compose_project} torn down")
