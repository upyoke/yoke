"""Project bootstrap setup mutations.

Hosts ``run_setup`` — the writer surface that creates the GitHub
secrets, configures the production environment, renders + copies the
workflow templates, and prints the TLS-provisioning runbook. Git and
SSH subprocess invocations route through ``_run`` so test suites can
intercept those via a single monkeypatch; GitHub mutations route
through the PAT-backed REST transport
(``gh_rest_transport.request_with_retry``) and PyNaCl-backed
``github_secrets_rest`` helper.
"""

from __future__ import annotations

import sys

from yoke_core.domain import bootstrap_project_helpers as helpers
from yoke_core.domain import gh_rest_transport, github_secrets_rest, project_scratch_dir
from yoke_core.domain.bootstrap_project_helpers import (
    BootstrapContext,
    SshKeyResolutionError,
    _load_setup_config,
    _persist_resolved_ssh_key_path,
    _probe_ssh_auth,
    _validate_ssh_key_parseable,
)
from yoke_core.domain.project_renderer import default_render_output_dir
from yoke_core.domain.project_renderer_settings import project_primary_domain_name
from yoke_core.domain.project_github_auth import (
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
    # against an explicit token from the project's capability_secrets row
    # rather than any host-CLI credential state.
    conn = helpers._connect()
    try:
        try:
            resolved = resolve_project_github_auth(project_slug, conn=conn)
        except ProjectGithubAuthError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            print(repair_command_hint(exc, project_slug), file=sys.stderr)
            return 2
    finally:
        conn.close()

    print("\n--- Step 1: Reading config from DB ---")
    print(f"  Project:     {cfg.display_name} ({project_slug})")
    print(f"  GitHub repo: {cfg.github_repo}")
    print(f"  Local path:  {cfg.repo_path}")
    print(f"  SSH host:    {cfg.ssh_host}")
    print(f"  SSH user:    {cfg.ssh_user}")
    print(f"  SSH key:     {cfg.ssh_key_path}")
    print(f"  Token:       {'[set]' if cfg.github_token else '[missing]'}")

    if not cfg.github_repo:
        print("Error: Missing github_repo for project", file=sys.stderr)
        return 2
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

    print(f"\n--- Step 2: Creating GitHub Secrets in {cfg.github_repo} ---")
    ssh_key_content = cfg.ssh_key_path.read_text()
    for name, value in (
        (f"{project_upper}_SSH_KEY", ssh_key_content),
        (f"{project_upper}_SSH_HOST", cfg.ssh_host),
        (f"{project_upper}_SSH_USER", cfg.ssh_user),
    ):
        print(f"  Setting {name}...", end="")
        try:
            github_secrets_rest.set_repo_secret(
                cfg.github_repo, name, value, token=resolved.token,
            )
        except gh_rest_transport.RestTransportError as exc:
            print(" FAILED", file=sys.stderr)
            print(f"Error: Failed to set {name} secret: {exc}", file=sys.stderr)
            return 2
        print(" done")

    _persist_resolved_ssh_key_path(ctx, cfg.ssh_key_path)
    print(f"  Recorded resolved key_path in project_capabilities.ssh: {cfg.ssh_key_path}")

    print("\n--- Step 3: Configuring production environment ---")
    try:
        user_resp = gh_rest_transport.request_with_retry(
            gh_rest_transport.RestRequest(method="GET", path="/user"),
            token=resolved.token,
        )
    except gh_rest_transport.RestTransportError as exc:
        print(f"Error: GitHub user lookup failed: {exc}", file=sys.stderr)
        return 2
    user_body = user_resp.body if isinstance(user_resp.body, dict) else {}
    login = str(user_body.get("login") or "").strip()
    raw_user_id = user_body.get("id")
    if not login:
        print("Error: Could not determine GitHub username via /user", file=sys.stderr)
        return 2
    if not isinstance(raw_user_id, int):
        print("Error: Could not determine GitHub user ID", file=sys.stderr)
        return 2
    print(f"  GitHub user: {login}")

    env_path = f"/repos/{cfg.github_repo}/environments/production"
    env_payload_full = {
        "wait_timer": 0,
        "prevent_self_review": False,
        "reviewers": [{"type": "User", "id": int(raw_user_id)}],
        "deployment_branch_policy": {
            "protected_branches": True,
            "custom_branch_policies": False,
        },
    }
    try:
        gh_rest_transport.request_with_retry(
            gh_rest_transport.RestRequest(
                method="PUT", path=env_path, body=env_payload_full,
            ),
            token=resolved.token,
        )
        print("  Creating production environment... done (with required reviewer)")
    except gh_rest_transport.RestTransportError:
        try:
            gh_rest_transport.request_with_retry(
                gh_rest_transport.RestRequest(
                    method="PUT", path=env_path, body={},
                ),
                token=resolved.token,
            )
            print(
                "  Creating production environment... done (without reviewer gate — plan does not support protection rules)"
            )
            print("  NOTE: Required reviewers need GitHub Enterprise Cloud for private repos.")
            print("  Deployments will auto-run on push to main with no approval pause.")
        except gh_rest_transport.RestTransportError as exc:
            print("  Creating production environment... FAILED", file=sys.stderr)
            print(f"Error: Failed to create production environment: {exc}", file=sys.stderr)
            return 2

    print("\n--- Step 4: Generating workflow files ---")
    with project_scratch_dir.scratch_subdir(
        "bootstrap-render", project_slug, delete=True,
    ) as render_dir:
        # Use the current interpreter so the render CLI imports in the same
        # environment as bootstrap_project itself.
        render = _run(
            [
                sys.executable,
                "-m", "yoke_core.tools.render_project",
                project_slug,
                "--write",
                "--only", "workflows",
                "--output-dir", str(render_dir),
            ],
            cwd=ctx.project_root,
        )
        print("  Rendering workflow templates...")
        for stream in (render.stdout, render.stderr):
            if not stream:
                continue
            for line in stream.splitlines():
                print(f"    {line}")
        if render.returncode != 0:
            print("Error: Failed to render workflow templates", file=sys.stderr)
            return 2

        workflow_source = render_dir / "workflows"
        workflow_dest = cfg.repo_path / ".github" / "workflows"
        workflow_dest.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for wf in sorted(workflow_source.glob("*.yml")):
            target = workflow_dest / wf.name
            target.write_text(wf.read_text())
            rel_target = f".github/workflows/{wf.name}"
            copied.append(rel_target)
            print(f"  Copied: {wf.name} -> {rel_target}")

    if not copied:
        print("Error: No workflow files were rendered", file=sys.stderr)
        return 2

    print(f"\n  Checking for changes in {project_slug} repo...")
    status = _run(["git", "status", "--porcelain", ".github/workflows/"], cwd=cfg.repo_path)
    if status.stdout.strip():
        print("  Committing workflow files...")
        for relpath in copied:
            add = _run(["git", "add", relpath], cwd=cfg.repo_path)
            if add.returncode != 0:
                print(f"Error: Failed to stage {relpath}", file=sys.stderr)
                return 2
        commit_message = (
            "ci: add Yoke-managed GitHub Actions workflow files\n\n"
            f"Generated by `python3 -m yoke_core.domain.bootstrap_project cli {project_slug}`.\n"
            "Source templates: templates/webapp/ops/\n"
            f"Regenerate: python3 -m yoke_core.tools.render_project {project_slug} --write --only workflows"
        )
        commit = _run(["git", "commit", "-m", commit_message], cwd=cfg.repo_path)
        if commit.returncode != 0:
            print("Error: Failed to commit workflow files", file=sys.stderr)
            return 2
        print(f"  Pushing to {cfg.github_repo} main...")
        push = _run(["git", "push", "origin", "main"], cwd=cfg.repo_path)
        if push.returncode == 0:
            print("  Push successful")
        else:
            print("  Push FAILED", file=sys.stderr)
            print(f"Error: Failed to push workflow files to {cfg.github_repo}", file=sys.stderr)
            return 2
    else:
        print("  No changes to commit (workflow files already up to date)")

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
    print("    1. Render the ops scripts locally:")
    print(f"       python3 -m yoke_core.tools.render_project {project_slug} --write --only ops")
    print()
    print("    2. Copy the rendered provision-tls.sh to the VPS:")
    default_ops_dir = default_render_output_dir(project_slug, create=False) / "ops"
    print(
        f"       scp {default_ops_dir}/provision-tls.sh "
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
