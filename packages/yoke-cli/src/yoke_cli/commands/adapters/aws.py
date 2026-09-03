"""``yoke aws`` source-dev/admin command adapters."""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from typing import Any, Dict, List, Optional

from yoke_cli.commands._helpers import ensure_handlers_loaded, parse_or_usage_error
from yoke_cli.commands.adapters.dev import DEFAULT_PROJECT_ID, PROJECT_ID_ENV
from yoke_cli.config import aws_cli_prerequisite
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef

AWS_EXEC_USAGE = "yoke aws exec [--project PROJECT] [--region REGION] -- <aws-args>"
AWS_ADMIN_LINK_USAGE = "yoke aws admin-link [--project PROJECT] [--region REGION]"
AWS_PREFLIGHT_USAGE = "yoke aws preflight"
AWS_ADMIN_STATUS_USAGE = "yoke aws admin-status [--project PROJECT] [--json]"
_AWS_ADMIN_CAPABILITY = "aws-admin"


def aws_admin_link(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke aws admin-link",
        description="Print the CloudFormation key link; keys appear as stack Outputs.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project slug or id the credential belongs to (informational).",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="AWS region the console opens in (default: $AWS_REGION or us-east-1).",
    )
    parsed = parse_or_usage_error(parser, args, AWS_ADMIN_LINK_USAGE)
    if parsed is None:
        return 2

    from yoke_cli.config import aws_admin_capability

    url = aws_admin_capability.quick_create_url(region=parsed.region)
    if url is None:
        print(
            "error: this build or distribution channel has no supported "
            "CloudFormation bootstrap link. Reinstall from a hosted Yoke "
            "release, or choose existing AWS credentials in `yoke onboard`.",
            file=sys.stderr,
        )
        return 1
    print(url)
    return 0


def aws_admin_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke aws admin-status",
        description=(
            "Report the control-plane row and machine key pair, name remedies, "
            "and verify them through boto3. Read `ready`; exit only says it ran."
        ),
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project slug or id (default: $YOKE_PROJECT_ID or yoke).",
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, AWS_ADMIN_STATUS_USAGE)
    if parsed is None:
        return 2

    from yoke_cli.config.project_slug_lookup import (
        ProjectSlugLookupError,
        resolve_project_slug,
    )

    try:
        slug = resolve_project_slug(parsed.project or _default_project())
        settings = _aws_admin_settings_or_none(slug)
    except (ProjectSlugLookupError, AwsExecAdapterError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report = aws_admin_status_report(slug, settings)
    if report["ready"]:
        _verify_aws_admin_identity(
            report,
            slug,
            str((settings or {}).get("region") or ""),
        )
    if parsed.json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _write_aws_admin_status(report)
    return 0


def aws_admin_status_report(
    slug: str, settings: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Compose both halves and the command that fills each missing one."""
    from yoke_cli.config import aws_admin_capability as capability

    present = list(capability.present_credential_keys(slug))
    missing_keys = list(capability.missing_credential_keys(slug))
    region = str((settings or {}).get("region") or "").strip()
    missing: list[str] = []
    remedy: list[str] = []
    if settings is None or not region:
        missing.append("capability_row")
        remedy.append(
            "yoke projects capability-settings merge "
            f"--project {slug} --cap-type {_AWS_ADMIN_CAPABILITY} "
            f"--set region={capability.default_region()}"
        )
    for key in missing_keys:
        remedy.append(
            f"yoke projects capability secret set --project {slug} "
            f"--cap-type {_AWS_ADMIN_CAPABILITY} --key {key} --value-stdin"
        )
    if missing_keys:
        missing.append("machine_secrets")
    return {
        "project": slug,
        "capability_row": {
            "present": settings is not None,
            "region": region or None,
            "account_id": str((settings or {}).get("account_id") or "") or None,
        },
        "machine_secrets": {
            "present": present,
            "missing": missing_keys,
            "directory": capability.credential_dir_display(slug),
        },
        "missing": missing,
        "ready": not missing,
        "remedy": remedy,
    }


def _verify_aws_admin_identity(
    report: Dict[str, Any],
    slug: str,
    region: str,
) -> None:
    from yoke_cli.config import aws_admin_capability as capability

    try:
        identity = capability.verify_caller_identity(slug, region)
    except capability.HostingVerificationError as exc:
        report["ready"] = False
        report["verification"] = {
            "checked": True,
            "ok": False,
            "reason": str(exc),
        }
        report["remedy"] = [
            f"yoke projects capability secret set --project {slug} "
            f"--cap-type {_AWS_ADMIN_CAPABILITY} --key {key} --value-stdin"
            for key in capability.REQUIRED_CREDENTIAL_KEYS
        ] + [f"yoke aws admin-status --project {slug} --json"]
        return
    report["verification"] = {
        "checked": True,
        "ok": True,
        "account": identity.account,
        "identity": identity.identity,
    }


def _write_aws_admin_status(report: Dict[str, Any]) -> None:
    row = report["capability_row"]
    secrets = report["machine_secrets"]
    if not row["present"]:
        row_line = "missing"
    elif not row["region"]:
        row_line = "present, no region declared"
    else:
        account = f", account {row['account_id']}" if row["account_id"] else ""
        row_line = f"present (region {row['region']}{account})"
    held = ", ".join(secrets["present"]) + " present" if secrets["present"] else "none"
    absent = f" · missing {', '.join(secrets['missing'])}" if secrets["missing"] else ""
    print(f"{_AWS_ADMIN_CAPABILITY} · project {report['project']}")
    print(f"  capability row     {row_line}")
    print(f"  machine secrets    {held}{absent} ({secrets['directory']})")
    verification = report.get("verification")
    if verification and verification["ok"]:
        print(
            "  identity check     verified · account "
            f"{verification['account']} · {verification['identity']}"
        )
    if report["ready"]:
        print("  ready              yes")
        return
    detail = (
        f"missing {', '.join(report['missing'])}"
        if report["missing"]
        else f"identity check failed · {verification['reason']}"
    )
    print(f"  ready              no · {detail}")
    print("")
    print("Recovery:")
    for command in report["remedy"]:
        print(f"  {command}")


def _aws_admin_settings_or_none(
    project: str, *, session_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Read the aws-admin settings document, or ``None`` when no row exists."""
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="projects.capability_settings.get",
        target=TargetRef(kind="global"),
        payload={"project": project, "cap_type": _AWS_ADMIN_CAPABILITY},
        actor=build_actor(session_id=session_id),
    )
    if response.success:
        parsed = json.loads(str((response.result or {}).get("settings_json") or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    code = response.error.code if response.error is not None else ""
    if code == "not_found":
        return None
    raise AwsExecAdapterError(
        response.error.message
        if response.error is not None
        else "capability settings read failed"
    )


def aws_exec(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke aws exec",
        description=(
            "Run the AWS CLI with the selected project's aws-admin "
            "capability credentials materialized only for the subprocess."
        ),
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project slug or id (default: $YOKE_PROJECT_ID or yoke).",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="AWS region (default: aws-admin capability settings.region).",
    )
    parser.add_argument("aws_args", nargs=argparse.REMAINDER)
    parsed = parse_or_usage_error(parser, args, AWS_EXEC_USAGE)
    if parsed is None:
        return 2

    aws_args = list(parsed.aws_args)
    if aws_args and aws_args[0] == "--":
        aws_args = aws_args[1:]
    if not aws_args:
        print("error: missing AWS CLI arguments after --", file=sys.stderr)
        print(f"Usage: {AWS_EXEC_USAGE}", file=sys.stderr)
        return 2

    project = parsed.project or _default_project()
    try:
        region = parsed.region or _aws_admin_region(project)
        if not region:
            raise AwsExecAdapterError(
                f"project '{project}' aws-admin capability settings declare "
                "no region; set settings.region or pass --region"
            )
        deploy_remote = importlib.import_module("yoke_core.domain.deploy_remote")
        env = deploy_remote.aws_machine_capability_env(project, region)
    except Exception as exc:
        print(f"error: aws-admin capability resolution failed: {exc}", file=sys.stderr)
        return 1

    try:
        cli = aws_cli_prerequisite.check_aws_cli()
    except aws_cli_prerequisite.AwsCliPrerequisiteError as exc:
        _print_prerequisite_refusal(exc)
        return 127
    try:
        completed = subprocess.run([cli.executable, *aws_args], env=env)
    except OSError as exc:
        # The preflight resolved this path a moment ago, so reaching here means
        # the install changed underneath us rather than that it was never there.
        print(
            f"error: the AWS CLI at {cli.executable} could not be run ({exc}).",
            file=sys.stderr,
        )
        print(
            f"  Reinstall it: {aws_cli_prerequisite.AWS_CLI_INSTALL_DOCS_URL}",
            file=sys.stderr,
        )
        return 127
    return int(completed.returncode)


def aws_preflight(args: List[str]) -> int:
    """Answer whether this machine can run the raw AWS CLI pass-through."""
    parser = argparse.ArgumentParser(
        prog="yoke aws preflight",
        description=(
            "Check that the AWS CLI used only by `yoke aws exec` is installed, "
            "on PATH, and runnable. Yoke's identity and VPS operations use "
            "boto3 in-process and do not require this executable."
        ),
    )
    parsed = parse_or_usage_error(parser, args, AWS_PREFLIGHT_USAGE)
    if parsed is None:
        return 2
    try:
        cli = aws_cli_prerequisite.check_aws_cli()
    except aws_cli_prerequisite.AwsCliPrerequisiteError as exc:
        _print_prerequisite_refusal(exc)
        return 127
    print(f"aws CLI ready: {cli.executable} ({cli.version})")
    return 0


def _print_prerequisite_refusal(
    exc: aws_cli_prerequisite.AwsCliPrerequisiteError,
) -> None:
    """Name the missing executable and the recovery, never a bare exit code."""
    for line in exc.report_lines():
        print(line, file=sys.stderr)


def _aws_admin_region(
    project: str, *, session_id: Optional[str] = None
) -> Optional[str]:
    """Read aws-admin settings.region through the active control-plane transport."""
    settings = _aws_admin_settings_or_none(project, session_id=session_id)
    region = str((settings or {}).get("region") or "").strip()
    return region or None


def _default_project() -> str:
    import os

    return os.environ.get(PROJECT_ID_ENV) or DEFAULT_PROJECT_ID


class AwsExecAdapterError(RuntimeError):
    """The requested AWS command lacks capability-owned configuration."""
