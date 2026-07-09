"""Project bootstrap verification probe.

Hosts ``run_verify`` — read-only checks against the live GitHub repo
and VPS that confirm the workflows, secrets, environments, and SSH
key fingerprints match the local DB state. Returns 0 when every
expected artifact exists; 1 on any failure. GitHub probes route
through the bearer-token REST transport
(``gh_rest_transport.request_with_retry``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from yoke_core.domain import bootstrap_project_helpers as helpers
from yoke_core.domain import gh_rest_transport
from yoke_core.domain.bootstrap_project_helpers import (
    BootstrapContext,
    _capability_settings,
    _connect,
    _decode_base64,
    _expected_workflow_names,
    _query_scalar,
    _resolve_project_identity,
    _warn,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)


def _run(*args, **kwargs):
    """Delegate to the canonical ``bootstrap_project_helpers._run``.

    See ``bootstrap_project_preflight._run`` for the rationale.
    """
    return helpers._run(*args, **kwargs)


def run_verify(
    ctx: BootstrapContext,
    *,
    github_repo: Optional[str] = None,
    ssh_user: Optional[str] = None,
    ssh_host: Optional[str] = None,
    ssh_key_path: Optional[str] = None,
    display_name: Optional[str] = None,
) -> int:
    print("\n--- Step 6: Verification ---")

    verify_pass = 0
    verify_fail = 0

    repo = github_repo or ""
    ssh_user = ssh_user or ""
    ssh_host = ssh_host or ""
    ssh_key_path = ssh_key_path or ""
    project_slug = ctx.project
    project_upper = ctx.project_upper
    display_name = display_name or ctx.project
    token: Optional[str] = None

    conn = _connect()
    try:
        ident = _resolve_project_identity(conn, ctx.project)
        project_slug = ident.slug
        project_upper = ident.slug.upper()
        # Resolve canonical project GitHub auth once on the active backend
        # connection; every REST probe runs against the explicit token.
        try:
            resolved = resolve_project_github_auth(project_slug, conn=conn)
            token = resolved.token
        except ProjectGithubAuthError as exc:
            _warn(
                f"project '{project_slug}' github auth not resolvable: {exc}. "
                f"Repair: {repair_command_hint(exc, project_slug)}"
            )

        p = helpers._p(conn)
        if not repo:
            repo = _query_scalar(
                conn, f"SELECT github_repo FROM projects WHERE id={p}", (ident.id,)
            ) or ""
        if display_name == ctx.project:
            display_name = (
                _query_scalar(conn, f"SELECT name FROM projects WHERE id={p}", (ident.id,))
                or project_slug
            )
        if not ssh_host or not ssh_user or not ssh_key_path:
            ssh_settings = _capability_settings(conn, project_slug, "ssh")
            ssh_host = ssh_host or str(ssh_settings.get("host", "") or "")
            ssh_user = ssh_user or str(ssh_settings.get("user", "") or "")
            if not ssh_key_path:
                env_key_name = f"{project_upper}_SSH_KEY_PATH"
                ssh_key_path = (
                    os.environ.get(env_key_name)
                    or str(ssh_settings.get("key_path", "") or "")
                )
    finally:
        conn.close()

    if ssh_key_path:
        ssh_key_path = str(Path(ssh_key_path).expanduser())

    def _rest_get(path: str):
        if not (repo and token):
            return None
        try:
            return gh_rest_transport.request_with_retry(
                gh_rest_transport.RestRequest(method="GET", path=path),
                token=token,
            )
        except gh_rest_transport.RestTransportError as exc:
            _warn(f"REST GET {path} failed: {exc}")
            return None

    workflow_names: list[str] = []
    wf_resp = _rest_get(f"/repos/{repo}/actions/workflows")
    if wf_resp is not None and isinstance(wf_resp.body, dict):
        for entry in wf_resp.body.get("workflows", []) or []:
            if isinstance(entry, dict):
                name = entry.get("name")
                if isinstance(name, str):
                    workflow_names.append(name)
    for wf_name in _expected_workflow_names(ctx, display_name):
        if wf_name and wf_name in workflow_names:
            verify_pass += 1
            print(f"[PASS] Workflow: {wf_name}")
        else:
            verify_fail += 1
            print(f"[FAIL] Workflow: {wf_name or 'unknown'} (not found in repo workflows)")

    secret_names: list[str] = []
    secrets_resp = _rest_get(f"/repos/{repo}/actions/secrets")
    if secrets_resp is not None and isinstance(secrets_resp.body, dict):
        for entry in secrets_resp.body.get("secrets", []) or []:
            if isinstance(entry, dict):
                name = entry.get("name")
                if isinstance(name, str):
                    secret_names.append(name)
    for suffix in ("SSH_KEY", "SSH_HOST", "SSH_USER"):
        secret_name = f"{project_upper}_{suffix}"
        if secret_name in secret_names:
            verify_pass += 1
            print(f"[PASS] Secret: {secret_name}")
        else:
            verify_fail += 1
            print(f"[FAIL] Secret: {secret_name} (not found in repo secrets)")

    for wf_file in (f"{project_slug}-deploy.yml", f"{project_slug}-smoke.yml"):
        content_resp = _rest_get(
            f"/repos/{repo}/contents/.github/workflows/{wf_file}",
        )
        wf_content = ""
        if content_resp is not None and isinstance(content_resp.body, dict):
            raw = content_resp.body.get("content")
            if isinstance(raw, str):
                wf_content = raw
        if wf_content:
            wf_yaml = _decode_base64(wf_content)
            if wf_yaml:
                if "workflow_dispatch" in wf_yaml:
                    verify_pass += 1
                    print(f"[PASS] Workflow trigger: {wf_file} has workflow_dispatch")
                else:
                    verify_fail += 1
                    print(f"[FAIL] Workflow trigger: {wf_file} missing workflow_dispatch")
                    print()
                    print("  ACTION REQUIRED:")
                    print(f"  The deploy workflow template should include workflow_dispatch.")
                    print("  This is required for Yoke's deploy pipeline (yoke_core.domain.github_actions trigger).")
                    print()
            else:
                _warn(f"Workflow trigger: could not decode {wf_file} content (skipping)")
        else:
            _warn(f"Workflow trigger: could not fetch {wf_file} from repo API (skipping)")

    if ssh_key_path and Path(ssh_key_path).is_file() and ssh_user and ssh_host:
        local_fp = _run(["ssh-keygen", "-lf", ssh_key_path]).stdout.split()
        local_fp = local_fp[1] if len(local_fp) >= 2 else ""
        if local_fp:
            remote_keys = _run(
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
                    "cat ~/.ssh/authorized_keys",
                ]
            ).stdout
            remote_fps = _run(["ssh-keygen", "-lf", "/dev/stdin"], stdin=remote_keys).stdout
            remote_vals = [line.split()[1] for line in remote_fps.splitlines() if len(line.split()) >= 2]
            if remote_vals:
                if local_fp in remote_vals:
                    verify_pass += 1
                    print("[PASS] SSH key fingerprint: local key matches VPS authorized_keys")
                else:
                    verify_fail += 1
                    print("[FAIL] SSH key fingerprint: local key NOT found in VPS authorized_keys")
                    print()
                    print("  ACTION REQUIRED:")
                    print(f"  Local key fingerprint:  {local_fp}")
                    print(f"  Remote fingerprint(s):  {' '.join(remote_vals)}")
                    print("  Add local key to the VPS:")
                    print(f"    ssh-copy-id -i {ssh_key_path} {ssh_user}@{ssh_host}")
                    print()
            else:
                _warn("SSH key fingerprint: could not read remote authorized_keys (skipping)")
        else:
            _warn("SSH key fingerprint: could not read local key fingerprint (skipping)")
    else:
        _warn("SSH key fingerprint: key file or SSH info not available (skipping)")

    env_names: list[str] = []
    production_has_reviewers = False
    envs_resp = _rest_get(f"/repos/{repo}/environments")
    if envs_resp is not None and isinstance(envs_resp.body, dict):
        for entry in envs_resp.body.get("environments", []) or []:
            if isinstance(entry, dict):
                name = entry.get("name")
                if isinstance(name, str):
                    env_names.append(name)
                if name == "production":
                    rules = entry.get("protection_rules") or []
                    for rule in rules:
                        if (
                            isinstance(rule, dict)
                            and rule.get("type") == "required_reviewers"
                        ):
                            production_has_reviewers = True
                            break
    if "production" in env_names:
        verify_pass += 1
        print("[PASS] Environment: production")
        if production_has_reviewers:
            verify_pass += 1
            print("[PASS] Environment: production has required reviewers")
        else:
            verify_fail += 1
            print("[FAIL] Environment: production missing required reviewers")
    else:
        verify_fail += 1
        print("[FAIL] Environment: production (not found)")

    total = verify_pass + verify_fail
    print()
    print(f"Verification: {verify_pass}/{total} checks passed")
    if verify_fail:
        print("Some verification checks failed. The pipeline may not be fully operational.")
        print(f"Investigate the failed checks above, then re-run: python3 -m yoke_core.domain.bootstrap_project cli {project_slug}")
        return 1

    print()
    print(f"{display_name} GitHub Actions pipeline is fully operational.")
    print(f"You can now conduct {project_slug} items through the full deployment flow.")
    return 0
