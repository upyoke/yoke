"""Project-owned Azure admin credentials and Azure CLI pass-through."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from yoke_cli.commands._helpers import ensure_handlers_loaded, parse_or_usage_error
from yoke_cli.config.project_selection import required_project_context
from yoke_cli.config.project_slug_lookup import (
    resolve_project_slug,
    ProjectSlugLookupError,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.azure_admin import (
    CAPABILITY,
    SETTING_KEYS,
    SECRET_KEY,
    AzureAdminError,
    azure_session,
    run_checked,
)
from yoke_contracts.azure_cli_prerequisite import AzureCliPrerequisiteError
from yoke_contracts.machine_config.capability_secret_store import (
    read_machine_capability_secret,
    MachineCapabilitySecretError,
)
from yoke_contracts.project_defaults import MissingProjectError

USAGES = {
    "admin-link": "yoke azure admin-link [--project PROJECT]",
    "admin-status": "yoke azure admin-status [--project PROJECT] [--json]",
    "exec": "yoke azure exec [--project PROJECT] -- <az-args>",
}


def _parse(verb, args):
    parser = argparse.ArgumentParser(prog=f"yoke azure {verb}")
    parser.add_argument(
        "--project", help="Project slug or id; defaults to this checkout."
    )
    if verb == "admin-status":
        parser.add_argument(
            "--json", action="store_true", help="Print readiness as JSON."
        )
    if verb == "exec":
        parser.add_argument(
            "az_args", nargs=argparse.REMAINDER, help="Azure CLI arguments after --."
        )
    return parse_or_usage_error(parser, args, USAGES[verb])


def _project(parsed):
    return resolve_project_slug(required_project_context(parsed.project))


def _settings(project):
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="projects.capability_settings.get",
        target=TargetRef(kind="global"),
        payload={"project": project, "cap_type": CAPABILITY},
        actor=build_actor(),
    )
    if response.success:
        settings = json.loads(str((response.result or {}).get("settings_json") or "{}"))
        if not isinstance(settings, dict):
            raise AzureAdminError(
                "azure-admin settings must be an object; run Azure admin-link and repair settings"
            )
        return settings
    if response.error and response.error.code == "not_found":
        return {}
    raise AzureAdminError(
        response.error.message if response.error else "Azure settings read failed"
    )


def azure_admin_link(args):
    parsed = _parse("admin-link", args)
    if parsed is None:
        return 2
    try:
        project = _project(parsed)
    except (MissingProjectError, ProjectSlugLookupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"
    )
    print(
        "Create or select a service principal, grant it the needed subscription/resource permissions, "
        "and copy its tenant id, client id, subscription id and client secret."
    )
    print(
        f"yoke projects capability-settings merge --project {project} --cap-type azure-admin "
        "--set tenant_id=TENANT --set client_id=CLIENT --set subscription_id=SUBSCRIPTION"
    )
    print(
        f"yoke projects capability secret set --project {project} --cap-type azure-admin "
        "--key client_secret --value-stdin"
    )
    print(f"yoke azure admin-status --project {project}")
    return 0


def azure_admin_status(args):
    parsed = _parse("admin-status", args)
    if parsed is None:
        return 2
    try:
        project = _project(parsed)
        settings = _settings(project)
        missing = [key for key in SETTING_KEYS if not settings.get(key)]
        if not read_machine_capability_secret(project, CAPABILITY, SECRET_KEY):
            missing.append(SECRET_KEY)
        report = {
            "project": project,
            "ready": False,
            "missing": missing,
            "remedy": [f"yoke azure admin-link --project {project}"],
        }
        if not missing:
            try:
                with azure_session(project, settings) as (command, env):
                    identity = run_checked(
                        lambda argv, **kw: subprocess.run(
                            argv, capture_output=True, text=True, **kw
                        ),
                        [*command, "account", "show", "--output", "json"],
                        env,
                        action="identity check",
                    )
                    account = json.loads(identity.stdout)
                    if (
                        account.get("id") != settings["subscription_id"]
                        or account.get("tenantId") != settings["tenant_id"]
                        or account.get("user", {}).get("name") != settings["client_id"]
                    ):
                        raise AzureAdminError(
                            "Azure identity mismatch; correct azure-admin settings and retry"
                        )
                    report.update(
                        ready=True,
                        subscription_id=account["id"],
                        tenant_id=account["tenantId"],
                        client_id=settings["client_id"],
                        remedy=[],
                    )
            except (AzureAdminError, AzureCliPrerequisiteError, ValueError) as exc:
                report["reason"] = str(exc)
        print(
            json.dumps(report, indent=2)
            if parsed.json
            else f"azure-admin · project {project}\n"
            + (
                "  ready: yes"
                if report["ready"]
                else f"  ready: no · {report.get('reason') or 'missing ' + ', '.join(missing)}\n"
                f"  Recovery: yoke azure admin-link --project {project}"
            )
        )
        return 0
    except (
        AzureAdminError,
        MachineCapabilitySecretError,
        MissingProjectError,
        ProjectSlugLookupError,
        ValueError,
    ) as exc:
        print(f"error: {exc}; run `yoke azure admin-link` and retry", file=sys.stderr)
        return 1


def azure_exec(args):
    parsed = _parse("exec", args)
    if parsed is None:
        return 2
    argv = parsed.az_args[1:] if parsed.az_args[:1] == ["--"] else parsed.az_args
    if not argv:
        print(
            f"error: missing Azure CLI arguments; usage: {USAGES['exec']}",
            file=sys.stderr,
        )
        return 2
    try:
        project = _project(parsed)
        with azure_session(project, _settings(project)) as (command, env):
            return subprocess.run([*command, *argv], env=env, check=False).returncode
    except (
        AzureAdminError,
        MachineCapabilitySecretError,
        AzureCliPrerequisiteError,
        MissingProjectError,
        ProjectSlugLookupError,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}; run `yoke azure admin-status` and retry", file=sys.stderr)
        return 1
