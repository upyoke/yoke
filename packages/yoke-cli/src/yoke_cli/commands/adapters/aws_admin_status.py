"""Readiness reporting and identity proof for AWS admin credentials."""

from __future__ import annotations
from typing import Any, Dict, Optional

_AWS_ADMIN_CAPABILITY = "aws-admin"


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
