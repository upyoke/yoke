"""Project bootstrap preflight checks.

Hosts ``run_preflight`` — the GitHub App auth/yoke-db/ssh/config probe that runs
before any mutation occurs. Each branch prints a ``[PASS]``/``[FAIL]``
line and accumulates a failure count so the operator sees every gap
in a single run. GitHub operations route through the bearer-token REST
transport (``yoke_core.domain.gh_rest_transport``).
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import bootstrap_project_helpers as helpers
from yoke_core.domain.bootstrap_project_helpers import (
    BootstrapContext,
    SshKeyResolutionError,
    _capability_secret,
    _capability_settings,
    _connect,
    _print_fail,
    _print_pass,
    _query_scalar,
    _resolve_project_identity,
    _resolve_ssh_key_path,
    _warn,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)
from yoke_core.domain.project_renderer import default_render_output_dir
from yoke_core.domain.project_renderer_settings import project_primary_domain_name


def _run(*args, **kwargs):
    """Delegate to the canonical ``bootstrap_project_helpers._run``.

    Looking the symbol up dynamically through the module object lets the
    test suite patch ``bootstrap_project_helpers._run`` and have the
    replacement visible to every caller in this file. A direct
    ``from .bootstrap_project_helpers import _run`` would freeze the
    binding at import time and silently bypass the patch.
    """
    return helpers._run(*args, **kwargs)


def run_preflight(ctx: BootstrapContext) -> int:
    project = ctx.project
    print(f"Yoke -- {project} Bootstrap Preflight")
    print("==================================")
    print()

    fail_count = 0

    github_repo = ""
    display_name = project
    ssh_settings: dict = {}
    ssh_host = ""
    ssh_user = ""
    ssh_key_path = ""

    conn = _connect()
    try:
        try:
            ident = _resolve_project_identity(conn, project)
        except LookupError:
            ident = None
        if ident is None:
            fail_count += 1
            _print_fail(
                f"projects table missing {project} record or github_repo not set",
                "Register the project in Yoke's DB:",
                f'  yoke projects create --slug {project} --name "<Display Name>" --github-repo <owner>/{project}',
                f"Re-run: python3 -m yoke_core.domain.bootstrap_project cli {project}",
            )
            print()
            print(f"Preflight failed — resolve the above {fail_count} item(s) before proceeding.")
            return 1
        project = ident.slug
        project_id = ident.id
        project_upper = ident.slug.upper()
        # Canonical project GitHub auth resolution is the sole GitHub
        # prerequisite: a typed resolver failure names the specific App
        # binding, installation, permission, or credential gap. The
        # caller-owned connection keeps bootstrap on active Postgres
        # authority instead of a DB path token.
        try:
            resolve_project_github_auth(project, conn=conn)
            _print_pass(f"project '{project}' github auth resolved (canonical)")
        except ProjectGithubAuthError as exc:
            fail_count += 1
            _print_fail(
                f"project '{project}' github auth not resolvable: {exc}",
                repair_command_hint(exc, project),
                f"Re-run: python3 -m yoke_core.domain.bootstrap_project cli {project}",
            )

        p = helpers._p(conn)
        github_repo = _query_scalar(
            conn, f"SELECT github_repo FROM projects WHERE id={p}", (project_id,)
        ) or ""
        display_name = _query_scalar(
            conn, f"SELECT name FROM projects WHERE id={p}", (project_id,)
        ) or project
        if github_repo:
            _print_pass(
                f"projects table has {project} record (github_repo: {github_repo})"
            )
        else:
            fail_count += 1
            _print_fail(
                f"projects table missing {project} record or github_repo not set",
                "Register the project in Yoke's DB:",
                f'  yoke projects create --slug {project} --name "<Display Name>" --github-repo <owner>/{project}',
                f"Re-run: python3 -m yoke_core.domain.bootstrap_project cli {project}",
            )

        github_settings = _capability_settings(conn, project, "github")
        if github_settings:
            _print_pass(
                f"project_capabilities has GitHub App entry for {project}"
            )
        else:
            fail_count += 1
            _print_fail(
                f"project_capabilities missing github entry for {project}",
                "Bind a GitHub App repository:",
                "  yoke projects github-binding bind "
                f"--project {project} --github-repo OWNER/REPO ...",
                f"Re-run: python3 -m yoke_core.domain.bootstrap_project cli {project}",
            )

        ssh_settings = _capability_settings(conn, project, "ssh")
        ssh_host = str(ssh_settings.get("host", "") or "")
        ssh_user = str(ssh_settings.get("user", "") or "")
        if ssh_settings:
            _print_pass(
                f"project_capabilities has ssh entry for {project} (host: {ssh_host}, user: {ssh_user})"
            )
        else:
            fail_count += 1
            _print_fail(
                f"project_capabilities missing ssh entry for {project}",
                "Add an ssh capability:",
                f'  python3 -m yoke_core.domain.projects capability-set-settings {project} ssh \'{{"host":"<VPS_IP>","user":"<SSH_USER>","key_path":"~/.ssh/id_rsa"}}\' --new',
                f"Re-run: python3 -m yoke_core.domain.bootstrap_project cli {project}",
            )
    finally:
        conn.close()

    project_upper = project.upper()
    env_key_name = f"{project_upper}_SSH_KEY_PATH"
    ssh_repair_hint = (
        f"Set {env_key_name}=/path/to/key, or record it in project_capabilities "
        "(preserves host/user):\n"
        f"  python3 -m yoke_core.domain.projects capability-merge-settings {project} ssh "
        "--set key_path=/path/to/key\n"
        f"Re-run: python3 -m yoke_core.domain.bootstrap_project cli {project}"
    )
    ssh_key_path = ""
    try:
        ssh_key_path = str(_resolve_ssh_key_path(project_upper, ssh_settings))
    except SshKeyResolutionError as exc:
        fail_count += 1
        _print_fail(str(exc), ssh_repair_hint)

    if ssh_key_path and Path(ssh_key_path).is_file():
        _print_pass(f"SSH key resolved at {ssh_key_path}")
    elif ssh_key_path:
        fail_count += 1
        _print_fail(f"SSH key not found at {ssh_key_path}", ssh_repair_hint)

    if ssh_key_path and Path(ssh_key_path).is_file() and ssh_host and ssh_user:
        ssh_ok = _run(
            [
                "ssh",
                "-o",
                "ConnectTimeout=5",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "BatchMode=yes",
                "-i",
                ssh_key_path,
                f"{ssh_user}@{ssh_host}",
                "echo ok",
            ]
        )
        if ssh_ok.returncode == 0:
            _print_pass(f"SSH connectivity to {ssh_user}@{ssh_host} verified")
        else:
            fail_count += 1
            _print_fail(
                f"Cannot SSH to {ssh_user}@{ssh_host}",
                "Verify:",
                f"  ssh -i {ssh_key_path} {ssh_user}@{ssh_host} 'echo ok'",
                "Common issues:",
                "  - Key not authorized on the VPS",
                "  - Firewall blocking port 22",
                f"  - Wrong key file (set {env_key_name})",
                f"Re-run: python3 -m yoke_core.domain.bootstrap_project cli {project}",
            )

    domain = project_primary_domain_name(project)
    if domain:
        _print_pass(f"Domain configured for TLS: {domain}")
        if Path(ssh_key_path).is_file() and ssh_host and ssh_user:
            tls_check = _run(
                [
                    "ssh",
                    "-o",
                    "ConnectTimeout=5",
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "BatchMode=yes",
                    "-i",
                    ssh_key_path,
                    f"{ssh_user}@{ssh_host}",
                    f"test -f /etc/letsencrypt/live/{domain}/fullchain.pem && echo 'exists' || echo 'missing'",
                ]
            )
            tls_state = tls_check.stdout.strip()
            if tls_state == "exists":
                _print_pass(f"Wildcard TLS certificate found on VPS for {domain}")
            elif tls_state == "missing":
                fail_count += 1
                _print_fail(
                    f"Wildcard TLS certificate not found on VPS for {domain}",
                    "Provision a wildcard cert using the provision-tls template:",
                    "  1. Render the ops scripts locally (gitignored outputs):",
                    f"     python3 -m yoke_core.tools.render_project {project} --write --only ops",
                    "  2. Copy provision-tls.sh to the VPS:",
                    "     scp "
                    f"{default_render_output_dir(project, create=False) / 'ops' / 'provision-tls.sh'} "
                    f"{ssh_user}@{ssh_host}:~/provision-tls.sh",
                    "  3. Create DNS credentials on the VPS:",
                    f"     ssh {ssh_user}@{ssh_host} 'sudo mkdir -p /etc/letsencrypt && echo \"dns_digitalocean_token = YOUR_TOKEN\" | sudo tee /etc/letsencrypt/dns-credentials.ini && sudo chmod 600 /etc/letsencrypt/dns-credentials.ini'",
                    "  4. Run the provisioning script:",
                    f"     ssh {ssh_user}@{ssh_host} 'sudo sh ~/provision-tls.sh'",
                    f"Re-run: python3 -m yoke_core.domain.bootstrap_project cli {project}",
                )
            else:
                _warn("Could not check TLS certificate on VPS (SSH issue) — skipping")
        else:
            _warn("TLS certificate check skipped (SSH not available yet)")
    else:
        fail_count += 1
        _print_fail(
            "Primary domain not configured in DB site settings",
            "Store sites.settings.domains[0].domain_name for this project.",
            f"Re-run: python3 -m yoke_core.domain.bootstrap_project cli {project}",
        )

    print()
    if fail_count:
        print(f"Preflight failed — resolve the above {fail_count} item(s) before proceeding.")
        return 1

    print("All preflight checks passed.")
    return 0
