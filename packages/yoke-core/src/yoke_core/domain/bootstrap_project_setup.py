"""Project bootstrap setup mutations.

Hosts ``run_setup`` — the writer surface that creates the GitHub
secrets, configures the production environment, installs the reusable
deployment Packs, and prints the TLS-provisioning runbook. SSH subprocess
invocations route through ``_run`` so test suites can
intercept those via a single monkeypatch; GitHub mutations route
through the bearer-token REST transport
(``gh_rest_transport.request_with_retry``) and PyNaCl-backed
``github_secrets_rest`` helper.
"""

from __future__ import annotations

import sys

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ENVIRONMENT_WRITE_PERMISSION_LEVELS,
    GITHUB_SECRETS_WRITE_PERMISSION_LEVELS,
)
from yoke_cli.packs import PackClientError, run_pack_operation
from yoke_cli.packs.receipt import load_receipt
from yoke_core.domain import bootstrap_project_helpers as helpers
from yoke_core.domain import gh_rest_transport, github_secrets_rest
from yoke_core.domain.bootstrap_project_helpers import (
    BootstrapContext,
    SshKeyResolutionError,
    _load_setup_config,
    _persist_resolved_ssh_key_path,
    _probe_ssh_auth,
    _validate_ssh_key_parseable,
)
from yoke_core.domain.project_renderer_settings import project_primary_domain_name
from yoke_core.domain.project_github_auth import (
    MissingPermission,
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)


def _run(*args, **kwargs):
    """Delegate to the canonical ``bootstrap_project_helpers._run``.

    See ``bootstrap_project_preflight._run`` for the rationale: a
    ``from .bootstrap_project_helpers import _run`` binding would
    freeze at import time and bypass test monkeypatches that retarget
    ``bootstrap_project_helpers._run``.
    """
    return helpers._run(*args, **kwargs)


def run_setup(ctx: BootstrapContext) -> int:
    try:
        cfg = _load_setup_config(ctx)
    except (FileNotFoundError, SshKeyResolutionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    project_slug = cfg.project
    project_upper = project_slug.upper()

    # Resolve canonical project GitHub auth once so REST calls below run
    # against a short-lived App installation token rather than any host-CLI
    # credential state.
    conn = helpers._connect()
    try:
        try:
            resolved = resolve_project_github_auth(
                project_slug,
                conn=conn,
                required_permissions=GITHUB_SECRETS_WRITE_PERMISSION_LEVELS,
            )
        except ProjectGithubAuthError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            print(repair_command_hint(exc, project_slug), file=sys.stderr)
            return 2
    finally:
        conn.close()
    repo = resolved.repo

    print("\n--- Step 1: Reading config from DB ---")
    print(f"  Project:     {cfg.display_name} ({project_slug})")
    print(f"  GitHub repo: {repo}")
    print(f"  Local path:  {cfg.repo_path}")
    print(f"  SSH host:    {cfg.ssh_host}")
    print(f"  SSH user:    {cfg.ssh_user}")
    print(f"  SSH key:     {cfg.ssh_key_path}")
    print(f"  GitHub App:  installation {resolved.installation_id or '[resolved]'}")

    if not cfg.repo_path.is_dir():
        print(f"Error: Project repo not found at {cfg.repo_path}", file=sys.stderr)
        return 2
    if not cfg.ssh_key_path.is_file():
        print(f"Error: SSH key not found at {cfg.ssh_key_path}", file=sys.stderr)
        return 2

    parse_ok, parse_msg = _validate_ssh_key_parseable(cfg.ssh_key_path)
    if not parse_ok:
        print(f"Error: SSH key at {cfg.ssh_key_path} did not parse: {parse_msg}", file=sys.stderr)
        return 2
    if not cfg.ssh_host or not cfg.ssh_user:
        print(f"Error: SSH host/user missing for project '{project_slug}' — set project_capabilities.ssh.{{host,user}} before setup.", file=sys.stderr)
        return 2
    probe_ok, probe_msg = _probe_ssh_auth(cfg.ssh_user, cfg.ssh_host, cfg.ssh_key_path)
    if not probe_ok:
        print(f"Error: SSH probe to {cfg.ssh_user}@{cfg.ssh_host} with {cfg.ssh_key_path} failed: {probe_msg}", file=sys.stderr)
        return 2

    print(f"\n--- Step 2: Creating GitHub Secrets in {repo} ---")
    ssh_key_content = cfg.ssh_key_path.read_text()
    for name, value in (
        (f"{project_upper}_SSH_KEY", ssh_key_content),
        (f"{project_upper}_SSH_HOST", cfg.ssh_host),
        (f"{project_upper}_SSH_USER", cfg.ssh_user),
    ):
        print(f"  Setting {name}...", end="")
        try:
            github_secrets_rest.set_repo_secret(
                repo, name, value, token=resolved.token,
            )
        except gh_rest_transport.RestTransportError as exc:
            print(" FAILED", file=sys.stderr)
            print(f"Error: Failed to set {name} secret: {exc}", file=sys.stderr)
            return 2
        print(" done")

    _persist_resolved_ssh_key_path(ctx, cfg.ssh_key_path)
    print(f"  Recorded resolved key_path in project_capabilities.ssh: {cfg.ssh_key_path}")

    print("\n--- Step 3: Configuring production environment (optional) ---")
    admin_resolved = None
    conn = helpers._connect()
    try:
        try:
            admin_resolved = resolve_project_github_auth(
                project_slug,
                conn=conn,
                required_permissions=GITHUB_ENVIRONMENT_WRITE_PERMISSION_LEVELS,
            )
        except MissingPermission:
            pass
        except ProjectGithubAuthError as exc:
            print(f"Error: optional environment auth failed: {exc}", file=sys.stderr)
            print(repair_command_hint(exc, project_slug), file=sys.stderr)
            return 2
    finally:
        conn.close()
    if admin_resolved is None:
        print("  Skipped: the default Yoke GitHub App grant does not request Administration.")
        print(
            "  To let Yoke create GitHub environments, reconnect the App with "
            "Administration: write, then rerun setup."
        )
        print(
            "  Or create the production environment under the repository's "
            "Settings → Environments page."
        )
    else:
        env_path = f"/repos/{admin_resolved.repo}/environments/production"
        try:
            gh_rest_transport.request_with_retry(
                gh_rest_transport.RestRequest(
                    method="PUT", path=env_path, body={},
                ),
                token=admin_resolved.token,
            )
            print("  Creating production environment... done")
            print(
                "  Configure required reviewers in GitHub settings if this "
                "deployment needs a human approval gate."
            )
        except gh_rest_transport.RestTransportError as exc:
            print("  Creating production environment... FAILED", file=sys.stderr)
            print(f"Error: Failed to create production environment: {exc}", file=sys.stderr)
            return 2

    print("\n--- Step 4: Installing project capability Packs ---")
    for pack in (
        "production-deploy",
        "smoke-testing",
        "ephemeral-environments",
        "vps-hosting",
    ):
        receipt = load_receipt(cfg.repo_path)
        installed = (receipt or {}).get("packs", {})
        operation = "update" if pack in installed else "get"
        print(f"  {operation.title()}: {pack}...", end="")
        try:
            report = run_pack_operation(
                cfg.repo_path,
                project=project_slug,
                pack=pack,
                operation=operation,
                apply=True,
            )
        except PackClientError as exc:
            print(" FAILED", file=sys.stderr)
            print(f"Error: Pack {operation} failed: {exc}", file=sys.stderr)
            return 2
        if report.get("refused") or not report.get("applied"):
            print(" CONFLICT", file=sys.stderr)
            print(
                f"Error: Pack {operation} requires manual conflict resolution; "
                f"preview with `yoke packs {operation} {pack} "
                f"{cfg.repo_path} --project {project_slug}`.",
                file=sys.stderr,
            )
            return 2
        print(" done")
        if report.get("projection_warning"):
            print(f"  Warning: {report['projection_warning']}", file=sys.stderr)
    print("  Review and commit the project-owned Pack changes in the project repo.")

    print("\n--- Step 5: TLS Certificate Provisioning ---")
    domain = project_primary_domain_name(project_slug)
    if not domain:
        print("  Domain not configured in DB site settings — skipping TLS provisioning")
        print(
            "  Store sites.settings.domains[0].domain_name before enabling TLS"
        )
        return 0

    tls_exists = _run(
        [
            "ssh",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "BatchMode=yes",
            "-i",
            str(cfg.ssh_key_path),
            f"{cfg.ssh_user}@{cfg.ssh_host}",
            f"test -f /etc/letsencrypt/live/{domain}/fullchain.pem && echo 'exists' || echo 'missing'",
        ]
    ).stdout.strip()
    if tls_exists == "exists":
        print(f"  Wildcard TLS certificate already exists for *.{domain} — skipping")
        return 0

    print(f"  Wildcard TLS certificate needed for *.{domain}\n")
    print("  The provision-tls.sh script automates certbot DNS-01 wildcard cert issuance.")
    print("  Run the following on the VPS (or provide to the operator):\n")
    print("    1. Review the VPS Hosting Pack guidance and project-owned script:")
    print(f"       {cfg.repo_path}/docs/packs/vps-hosting/README.md")
    print()
    print("    2. Copy provision-tls.sh to the VPS:")
    print(
        f"       scp {cfg.repo_path}/ops/provision-tls.sh "
        f"{cfg.ssh_user}@{cfg.ssh_host}:~/provision-tls.sh"
    )
    print()
    print("    3. Create DNS API credentials on the VPS:")
    print(f"       ssh {cfg.ssh_user}@{cfg.ssh_host}")
    print("       sudo mkdir -p /etc/letsencrypt")
    print("       echo 'dns_digitalocean_token = YOUR_DO_API_TOKEN' | sudo tee /etc/letsencrypt/dns-credentials.ini")
    print("       sudo chmod 600 /etc/letsencrypt/dns-credentials.ini")
    print()
    print("    4. Run the provisioning script:")
    print("       sudo sh ~/provision-tls.sh")
    print()
    print("  The script will:")
    print("    - Install certbot + DNS plugin if needed")
    print(f"    - Request a wildcard cert for *.{domain} via DNS-01 challenge")
    print("    - Configure automatic renewal with nginx reload")
    print()
    return 0
