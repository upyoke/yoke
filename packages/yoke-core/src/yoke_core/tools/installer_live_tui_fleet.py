"""EC2 fleet preparation for live installer/TUI validation campaigns."""

from __future__ import annotations

import argparse
import re
import secrets
import shlex
import stat
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from yoke_contracts.api_urls import HOSTED_PROD_URL, HOSTED_STAGE_URL

from yoke_core.domain import json_helper
from yoke_core.domain.deploy_remote import aws_capability_env


DEFAULT_PROJECT = "yoke"
DEFAULT_REGION = "us-east-1"
DEFAULT_ENDPOINT = "stage"
DEFAULT_BASE_URL = HOSTED_STAGE_URL
DEFAULT_DISTRO = "amazon-linux-2023"
DEFAULT_ARCH = "x86_64"
DEFAULT_SSH_USER = "ec2-user"
DEFAULT_INSTANCE_TYPE = "t3.small"
DEFAULT_MAX_COUNT = 20
PURPOSE_TAG = "yoke-installer-tui-test"
SUPPORTED_PROFILES = {
    "bare-linux",
    "bare-no-curl",
    "bare-no-uv",
    "fault-injection",
    "prepared-path-broken",
    "prepared-screen-term",
    "prepared-stored-state",
    "prepared-yoke",
    "prepared-no-git",
    "prepared-no-git-no-sudo",
    "prepared-git",
}
RESETTABLE_PROFILES = {
    "bare-linux",
    "bare-no-uv",
    "prepared-path-broken",
    "prepared-screen-term",
    "prepared-stored-state",
    "prepared-yoke",
    "prepared-no-git",
    "prepared-git",
}
HOST_METADATA_KEYS = (
    "fault_injection",
    "terminal_profile",
    "stored_state",
    "package_install",
)
SSH_OPTIONS = (
    "StrictHostKeyChecking=accept-new",
    "UserKnownHostsFile=/dev/null",
    "ConnectTimeout=10",
    "BatchMode=yes",
)
AMAZON_LINUX_AMI_PARAMS = {
    "x86_64": "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64",
    "aarch64": "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64",
}
UBUNTU_2404_AMI_PARAMS = {
    "x86_64": "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id",
    "aarch64": "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id",
}
DISTRO_AMI_PARAMS = {
    "amazon-linux-2023": AMAZON_LINUX_AMI_PARAMS,
    "ubuntu-24.04": UBUNTU_2404_AMI_PARAMS,
}
DISTRO_SSH_USERS = {
    "amazon-linux-2023": DEFAULT_SSH_USER,
    "ubuntu-24.04": "ubuntu",
}
REMOTE_YOKE_TOKEN_PATH = "/tmp/yoke-api.token"
REMOTE_GITHUB_TOKEN_PATH = "/tmp/yoke-github.token"
LOCAL_TOKEN_STAGING_ROOT = Path("/tmp")
LOCAL_GITHUB_TOKEN_PATH = LOCAL_TOKEN_STAGING_ROOT / "yoke-github.token"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class StoredStateProfile:
    yoke_token_file: Path
    github_token_file: Path | None = None
    github_repo: str | None = None


class CommandRunner:
    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: int = 600,
    ) -> CommandResult:
        completed = subprocess.run(
            list(argv),
            env=dict(env) if env is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )


def build_fleet_plan(
    *,
    campaign_id: str,
    campaign_root: Path,
    count: int,
    profile: str,
    endpoint: str = DEFAULT_ENDPOINT,
    region: str = DEFAULT_REGION,
    distro: str = DEFAULT_DISTRO,
    arch: str = DEFAULT_ARCH,
    instance_type: str = DEFAULT_INSTANCE_TYPE,
    expires_at: str | None = None,
    ssh_cidr: str | None = None,
) -> dict[str, object]:
    _validate_campaign_id(campaign_id)
    _validate_count(count)
    _validate_profile(profile)
    ami_params = _ami_params_for_distro(distro)
    if arch not in ami_params:
        raise ValueError(f"unsupported arch for {distro}: {arch}")
    return {
        "campaign_id": campaign_id,
        "campaign_root": str(campaign_root),
        "count": count,
        "profile": profile,
        "endpoint": endpoint,
        "base_url": _base_url_for_endpoint(endpoint),
        "region": region,
        "distro": distro,
        "arch": arch,
        "instance_type": instance_type,
        "ami_parameter": ami_params[arch],
        "ssh_user": _ssh_user_for_distro(distro),
        "purpose_tag": PURPOSE_TAG,
        "expires_at": expires_at or default_expires_at(),
        "ssh_cidr": ssh_cidr,
        "key_dir": str(default_key_dir(campaign_id)),
        "execute_required": True,
    }


def prepare_fleet(
    *,
    campaign_id: str,
    campaign_root: Path,
    count: int,
    profile: str,
    endpoint: str = DEFAULT_ENDPOINT,
    project: str = DEFAULT_PROJECT,
    region: str = DEFAULT_REGION,
    distro: str = DEFAULT_DISTRO,
    arch: str = DEFAULT_ARCH,
    instance_type: str = DEFAULT_INSTANCE_TYPE,
    ssh_cidr: str | None = None,
    key_dir: Path | None = None,
    yoke_token_file: Path | None = None,
    github_token_file: Path | None = None,
    github_repo: str | None = None,
    runner: CommandRunner | None = None,
    public_ip_fetcher: Callable[[], str] | None = None,
) -> dict[str, object]:
    selected_runner = runner or CommandRunner()
    stored_state = _stored_state_profile(
        profile,
        yoke_token_file=yoke_token_file,
        github_token_file=github_token_file,
        github_repo=github_repo,
    )
    plan = build_fleet_plan(
        campaign_id=campaign_id,
        campaign_root=campaign_root,
        count=count,
        profile=profile,
        endpoint=endpoint,
        region=region,
        distro=distro,
        arch=arch,
        instance_type=instance_type,
        ssh_cidr=ssh_cidr,
    )
    env = aws_capability_env(project, region)
    suffix = f"{_safe_slug(campaign_id)}-{secrets.token_hex(3)}"
    key_name = f"yoke-tui-{suffix}"
    sg_name = f"yoke-tui-{suffix}"
    resolved_key_dir = key_dir or default_key_dir(campaign_id)
    key_path = resolved_key_dir / f"{key_name}.pem"
    resolved_cidr = ssh_cidr or f"{(public_ip_fetcher or fetch_public_ip)()}/32"
    created: dict[str, object] = {
        "project": project,
        "region": region,
        "key_name": key_name,
        "key_path": str(key_path),
        "security_group_id": None,
        "instance_ids": [],
    }
    try:
        ami = _aws_text(
            selected_runner,
            env,
            [
                "ssm",
                "get-parameter",
                "--name",
                str(plan["ami_parameter"]),
                "--query",
                "Parameter.Value",
                "--output",
                "text",
            ],
        )
        vpc_id = _aws_text(
            selected_runner,
            env,
            [
                "ec2",
                "describe-vpcs",
                "--filters",
                "Name=isDefault,Values=true",
                "--query",
                "Vpcs[0].VpcId",
                "--output",
                "text",
            ],
        )
        subnet_id = _aws_text(
            selected_runner,
            env,
            [
                "ec2",
                "describe-subnets",
                "--filters",
                f"Name=vpc-id,Values={vpc_id}",
                "Name=default-for-az,Values=true",
                "--query",
                "Subnets[0].SubnetId",
                "--output",
                "text",
            ],
        )
        private_key = _aws_text(
            selected_runner,
            env,
            [
                "ec2",
                "create-key-pair",
                "--key-name",
                key_name,
                "--query",
                "KeyMaterial",
                "--output",
                "text",
            ],
            secret_stdout=True,
        )
        _write_private_key(key_path, private_key)
        sg_id = _aws_text(
            selected_runner,
            env,
            [
                "ec2",
                "create-security-group",
                "--group-name",
                sg_name,
                "--description",
                "installer live TUI validation",
                "--vpc-id",
                vpc_id,
                "--query",
                "GroupId",
                "--output",
                "text",
            ],
        )
        created["security_group_id"] = sg_id
        _aws_text(
            selected_runner,
            env,
            [
                "ec2",
                "authorize-security-group-ingress",
                "--group-id",
                sg_id,
                "--protocol",
                "tcp",
                "--port",
                "22",
                "--cidr",
                resolved_cidr,
            ],
        )
        instance_ids = _aws_text(
            selected_runner,
            env,
            [
                "ec2",
                "run-instances",
                "--image-id",
                ami,
                "--instance-type",
                instance_type,
                "--count",
                str(count),
                "--key-name",
                key_name,
                "--security-group-ids",
                sg_id,
                "--subnet-id",
                subnet_id,
                "--associate-public-ip-address",
                "--tag-specifications",
                _tag_spec("instance", campaign_id, plan["expires_at"]),
                "--tag-specifications",
                _tag_spec("volume", campaign_id, plan["expires_at"]),
                "--query",
                "Instances[].InstanceId",
                "--output",
                "text",
            ],
        ).split()
        created["instance_ids"] = instance_ids
        _aws_text(
            selected_runner,
            env,
            ["ec2", "wait", "instance-running", "--instance-ids", *instance_ids],
        )
        public_ips = _aws_text(
            selected_runner,
            env,
            [
                "ec2",
                "describe-instances",
                "--instance-ids",
                *instance_ids,
                "--query",
                "Reservations[].Instances[].PublicIpAddress",
                "--output",
                "text",
            ],
        ).split()
        if len(public_ips) != len(instance_ids):
            raise RuntimeError(
                "AWS did not return one public IP per instance "
                f"(instances={len(instance_ids)} ips={len(public_ips)})"
            )
        hosts = []
        ssh_user = str(plan["ssh_user"])
        for index, (instance_id, public_ip) in enumerate(
            zip(instance_ids, public_ips), start=1
        ):
            _wait_for_ssh(selected_runner, key_path, public_ip, ssh_user=ssh_user)
            _bootstrap_host(
                selected_runner,
                key_path,
                public_ip,
                profile=profile,
                base_url=str(plan["base_url"]),
                endpoint=endpoint,
                distro=distro,
                ssh_user=ssh_user,
                stored_state=stored_state,
            )
            host_metadata = _host_metadata(profile, stored_state=stored_state)
            hosts.append(
                {
                    "host_id": f"tui-linux-{index:03d}",
                    "instance_id": instance_id,
                    "public_ip": public_ip,
                    "key_path": str(key_path),
                    "distro": distro,
                    "arch": arch,
                    "ssh_user": ssh_user,
                    "profile": profile,
                    "endpoint": endpoint,
                    "lease_state": "available",
                    **host_metadata,
                }
            )
        ledger = {
            **plan,
            "project": project,
            "key_name": key_name,
            "key_path": str(key_path),
            "security_group_id": sg_id,
            "ssh_cidr": resolved_cidr,
            "hosts": hosts,
            "created_at": _now_iso(),
        }
        campaign_root.mkdir(parents=True, exist_ok=True)
        ledger_path = campaign_root / "host-ledger.json"
        json_helper.dump_path(ledger_path, ledger)
        return {"ok": True, "ledger_path": str(ledger_path), "ledger": ledger}
    except Exception:
        _cleanup_created(selected_runner, env, created)
        raise


def cleanup_fleet(
    *,
    ledger_path: Path,
    project: str = DEFAULT_PROJECT,
    region: str = DEFAULT_REGION,
    runner: CommandRunner | None = None,
    remove_key_file: bool = True,
) -> dict[str, object]:
    selected_runner = runner or CommandRunner()
    env = aws_capability_env(project, region)
    ledger = json_helper.load_path(ledger_path)
    if not isinstance(ledger, dict):
        raise ValueError(f"ledger root must be a JSON object: {ledger_path}")
    instance_ids = [
        str(host["instance_id"])
        for host in ledger.get("hosts", [])
        if isinstance(host, dict) and host.get("instance_id")
    ]
    sg_id = str(ledger.get("security_group_id") or "")
    key_name = str(ledger.get("key_name") or "")
    if instance_ids:
        _aws_text(
            selected_runner,
            env,
            ["ec2", "terminate-instances", "--instance-ids", *instance_ids],
        )
        _aws_text(
            selected_runner,
            env,
            ["ec2", "wait", "instance-terminated", "--instance-ids", *instance_ids],
        )
    if sg_id:
        _aws_text(
            selected_runner,
            env,
            ["ec2", "delete-security-group", "--group-id", sg_id],
        )
    if key_name:
        _aws_text(
            selected_runner,
            env,
            ["ec2", "delete-key-pair", "--key-name", key_name],
        )
    key_path = Path(str(ledger.get("key_path") or "")).expanduser()
    if remove_key_file and key_path.is_file():
        key_path.unlink()
    return {
        "ok": True,
        "terminated_instances": instance_ids,
        "deleted_security_group": sg_id,
        "deleted_key_pair": key_name,
        "removed_key_file": bool(remove_key_file and key_path and not key_path.exists()),
    }


def reset_fleet_host(
    *,
    ledger_path: Path,
    target_profile: str,
    host_id: str | None = None,
    yoke_token_file: Path | None = None,
    github_token_file: Path | None = None,
    github_repo: str | None = None,
    runner: CommandRunner | None = None,
) -> dict[str, object]:
    selected_runner = runner or CommandRunner()
    _validate_reset_profile(target_profile)
    ledger = _load_ledger(ledger_path)
    host = _select_ledger_host(ledger, host_id)
    key_path = Path(
        str(host.get("key_path") or ledger.get("key_path") or "")
    ).expanduser()
    if not key_path.is_file():
        raise ValueError(f"ledger key_path is not readable: {key_path}")
    public_ip = str(host.get("public_ip") or "")
    if not public_ip:
        raise ValueError("ledger host has no public_ip")
    ssh_user = _ssh_user_for_ledger_host(ledger, host)
    endpoint = str(host.get("endpoint") or ledger.get("endpoint") or DEFAULT_ENDPOINT)
    stored_state = _stored_state_profile_for_reset(
        target_profile,
        host=host,
        endpoint=endpoint,
        yoke_token_file=yoke_token_file,
        github_token_file=github_token_file,
        github_repo=github_repo,
    )
    _run_ssh(
        selected_runner,
        key_path,
        public_ip,
        _reset_command(target_profile),
        ssh_user=ssh_user,
        timeout=300,
    )
    base_url = str(ledger.get("base_url") or DEFAULT_BASE_URL)
    distro = str(host.get("distro") or ledger.get("distro") or DEFAULT_DISTRO)
    _bootstrap_host(
        selected_runner,
        key_path,
        public_ip,
        profile=target_profile,
        base_url=base_url,
        endpoint=endpoint,
        distro=distro,
        ssh_user=ssh_user,
        stored_state=stored_state,
    )
    _record_reset_profile(
        ledger_path=ledger_path,
        ledger=ledger,
        host=host,
        target_profile=target_profile,
        endpoint=endpoint,
        stored_state=stored_state,
    )
    return {
        "ok": True,
        "host_id": str(host.get("host_id") or ""),
        "instance_id": str(host.get("instance_id") or ""),
        "target_profile": target_profile,
    }


def default_expires_at(hours: int = 8) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat().replace(
        "+00:00", "Z"
    )


def default_key_dir(campaign_id: str) -> Path:
    return Path.home() / ".yoke" / "secrets" / "installer-live-tui" / campaign_id


def fetch_public_ip() -> str:
    with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=30) as resp:
        return resp.read().decode("utf-8").strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.tools.installer_live_tui_fleet",
        description="Prepare or clean up EC2 hosts for live installer/TUI tests.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("fleet-plan")
    _add_common_fleet_args(plan)
    plan.add_argument("--json", action="store_true")

    prepare = subparsers.add_parser("fleet-prepare")
    _add_common_fleet_args(prepare)
    prepare.add_argument("--project", default=DEFAULT_PROJECT)
    prepare.add_argument("--key-dir", type=Path)
    prepare.add_argument("--yoke-token-file", type=Path)
    prepare.add_argument("--github-token-file", type=Path)
    prepare.add_argument("--github-repo")
    prepare.add_argument("--execute", action="store_true")
    prepare.add_argument("--json", action="store_true")

    cleanup = subparsers.add_parser("fleet-cleanup")
    cleanup.add_argument("--ledger", required=True, type=Path)
    cleanup.add_argument("--project", default=DEFAULT_PROJECT)
    cleanup.add_argument("--region", default=DEFAULT_REGION)
    cleanup.add_argument("--execute", action="store_true")
    cleanup.add_argument("--keep-key-file", action="store_true")
    cleanup.add_argument("--json", action="store_true")

    reset = subparsers.add_parser("fleet-reset")
    reset.add_argument("--ledger", required=True, type=Path)
    reset.add_argument("--host-id")
    reset.add_argument("--target-profile", default="bare-no-uv")
    reset.add_argument("--yoke-token-file", type=Path)
    reset.add_argument("--github-token-file", type=Path)
    reset.add_argument("--github-repo")
    reset.add_argument("--execute", action="store_true")
    reset.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "fleet-plan":
            payload = build_fleet_plan(**_common_plan_kwargs(args))
            return _emit(payload, args.json, f"Planned {payload['count']} hosts")
        if args.command == "fleet-prepare":
            if not args.execute:
                payload = build_fleet_plan(**_common_plan_kwargs(args))
                payload["dry_run"] = True
                return _emit(
                    payload,
                    args.json,
                    "Dry run only; pass --execute to create EC2 resources.",
                )
            payload = prepare_fleet(
                **_common_plan_kwargs(args),
                project=args.project,
                key_dir=args.key_dir.expanduser() if args.key_dir else None,
                yoke_token_file=(
                    args.yoke_token_file.expanduser()
                    if args.yoke_token_file
                    else None
                ),
                github_token_file=(
                    args.github_token_file.expanduser()
                    if args.github_token_file
                    else None
                ),
                github_repo=args.github_repo,
            )
            return _emit(payload, args.json, f"Prepared fleet: {payload['ledger_path']}")
        if args.command == "fleet-cleanup":
            if not args.execute:
                ledger = json_helper.load_path(args.ledger.expanduser())
                payload = {"dry_run": True, "ledger": ledger}
                return _emit(
                    payload,
                    args.json,
                    "Dry run only; pass --execute to delete EC2 resources.",
                )
            payload = cleanup_fleet(
                ledger_path=args.ledger.expanduser(),
                project=args.project,
                region=args.region,
                remove_key_file=not args.keep_key_file,
            )
            return _emit(payload, args.json, "Cleaned up fleet")
        if args.command == "fleet-reset":
            if not args.execute:
                ledger = json_helper.load_path(args.ledger.expanduser())
                payload = {
                    "dry_run": True,
                    "ledger": ledger,
                    "target_profile": args.target_profile,
                }
                return _emit(
                    payload,
                    args.json,
                    "Dry run only; pass --execute to reset the host.",
                )
            payload = reset_fleet_host(
                ledger_path=args.ledger.expanduser(),
                host_id=args.host_id,
                target_profile=args.target_profile,
                yoke_token_file=(
                    args.yoke_token_file.expanduser()
                    if args.yoke_token_file
                    else None
                ),
                github_token_file=(
                    args.github_token_file.expanduser()
                    if args.github_token_file
                    else None
                ),
                github_repo=args.github_repo,
            )
            return _emit(payload, args.json, "Reset fleet host")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command: {args.command}")


def _add_common_fleet_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--campaign-root", required=True, type=Path)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--profile", default="prepared-git")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--distro", default=DEFAULT_DISTRO)
    parser.add_argument("--arch", default=DEFAULT_ARCH)
    parser.add_argument("--instance-type", default=DEFAULT_INSTANCE_TYPE)
    parser.add_argument("--ssh-cidr")


def _common_plan_kwargs(args: argparse.Namespace) -> dict[str, object]:
    return {
        "campaign_id": args.campaign_id,
        "campaign_root": args.campaign_root.expanduser(),
        "count": args.count,
        "profile": args.profile,
        "endpoint": args.endpoint,
        "region": args.region,
        "distro": args.distro,
        "arch": args.arch,
        "instance_type": args.instance_type,
        "ssh_cidr": args.ssh_cidr,
    }


def _base_url_for_endpoint(endpoint: str) -> str:
    if endpoint == "stage":
        return DEFAULT_BASE_URL
    if endpoint == "prod":
        return HOSTED_PROD_URL
    if endpoint.startswith("https://"):
        return endpoint.rstrip("/")
    raise ValueError(f"unsupported endpoint: {endpoint}")


def _ami_params_for_distro(distro: str) -> Mapping[str, str]:
    try:
        return DISTRO_AMI_PARAMS[distro]
    except KeyError as exc:
        supported = ", ".join(sorted(DISTRO_AMI_PARAMS))
        raise ValueError(f"unsupported distro: {distro} (supported: {supported})") from exc


def _ssh_user_for_distro(distro: str) -> str:
    try:
        return DISTRO_SSH_USERS[distro]
    except KeyError as exc:
        supported = ", ".join(sorted(DISTRO_SSH_USERS))
        raise ValueError(f"unsupported distro: {distro} (supported: {supported})") from exc


def _ssh_user_for_ledger_host(
    ledger: Mapping[str, object],
    host: Mapping[str, object],
) -> str:
    explicit = str(host.get("ssh_user") or ledger.get("ssh_user") or "")
    if explicit:
        return explicit
    distro = str(host.get("distro") or ledger.get("distro") or DEFAULT_DISTRO)
    return _ssh_user_for_distro(distro)


def _bootstrap_host(
    runner: CommandRunner,
    key_path: Path,
    public_ip: str,
    *,
    profile: str,
    base_url: str,
    endpoint: str,
    distro: str,
    ssh_user: str,
    stored_state: StoredStateProfile | None,
) -> None:
    packages = ["tmux"]
    if _profile_needs_git(profile):
        packages.append("git")
    package_command = _package_bootstrap_command(
        distro,
        packages,
        ensure_curl=_profile_needs_curl(profile),
    )
    _run_ssh(
        runner,
        key_path,
        public_ip,
        package_command,
        ssh_user=ssh_user,
        timeout=600,
    )
    if _profile_needs_yoke(profile):
        command = (
            "export YOKE_INSTALL_YES=1 YOKE_NO_ONBOARD=1; "
            f"curl -fsSL {base_url}/install -o /tmp/yoke-install && "
            f"YOKE_INSTALL_BASE_URL={base_url} YOKE_CHANNEL=latest "
            "sh /tmp/yoke-install --yes --no-onboard"
        )
        _run_ssh(runner, key_path, public_ip, command, ssh_user=ssh_user, timeout=900)
    if profile == "bare-no-curl":
        _run_ssh(
            runner,
            key_path,
            public_ip,
            _disable_curl_command(),
            ssh_user=ssh_user,
            timeout=120,
        )
    if profile == "prepared-path-broken":
        _run_ssh(
            runner,
            key_path,
            public_ip,
            _path_broken_profile_command(),
            ssh_user=ssh_user,
            timeout=120,
        )
    if profile == "prepared-no-git":
        _run_ssh(
            runner,
            key_path,
            public_ip,
            _no_git_profile_command(distro),
            ssh_user=ssh_user,
            timeout=300,
        )
    if profile == "prepared-no-git-no-sudo":
        _run_ssh(
            runner,
            key_path,
            public_ip,
            _no_git_no_sudo_profile_command(),
            ssh_user=ssh_user,
            timeout=120,
        )
    if profile == "prepared-stored-state" and stored_state is not None:
        _copy_file_to_remote(
            runner,
            key_path,
            public_ip,
            stored_state.yoke_token_file,
            REMOTE_YOKE_TOKEN_PATH,
            ssh_user=ssh_user,
        )
        if stored_state.github_token_file is not None:
            _copy_file_to_remote(
                runner,
                key_path,
                public_ip,
                stored_state.github_token_file,
                REMOTE_GITHUB_TOKEN_PATH,
                ssh_user=ssh_user,
            )
        _run_ssh(
            runner,
            key_path,
            public_ip,
            _stored_state_profile_command(
                base_url=base_url,
                endpoint=endpoint,
                has_github_token=stored_state.github_token_file is not None,
                github_repo=stored_state.github_repo,
            ),
            ssh_user=ssh_user,
            timeout=900,
        )


def _package_bootstrap_command(
    distro: str,
    packages: Sequence[str],
    *,
    ensure_curl: bool,
) -> str:
    joined_packages = " ".join(packages)
    if distro == "amazon-linux-2023":
        curl_command = (
            "command -v curl >/dev/null || sudo dnf install -y curl-minimal; "
            if ensure_curl
            else ""
        )
        return curl_command + f"sudo dnf install -y {joined_packages}"
    if distro == "ubuntu-24.04":
        curl_package = " $curl_pkg" if ensure_curl else ""
        curl_selector = (
            "if command -v curl >/dev/null; then curl_pkg=''; "
            "else curl_pkg='curl'; fi; "
            if ensure_curl
            else ""
        )
        return (
            "sudo apt-get update; "
            + curl_selector
            + "sudo env DEBIAN_FRONTEND=noninteractive "
            + f"apt-get install -y {joined_packages}{curl_package}"
        )
    _ami_params_for_distro(distro)
    raise AssertionError(f"unhandled distro: {distro}")


def _profile_needs_git(profile: str) -> bool:
    return profile in {"prepared-git", "prepared-stored-state"}


def _profile_needs_curl(profile: str) -> bool:
    return profile != "bare-no-curl"


def _profile_needs_yoke(profile: str) -> bool:
    return profile.startswith("prepared") or profile == "fault-injection"


def _stored_state_profile(
    profile: str,
    *,
    yoke_token_file: Path | None,
    github_token_file: Path | None,
    github_repo: str | None,
) -> StoredStateProfile | None:
    if profile != "prepared-stored-state":
        if yoke_token_file is not None or github_token_file is not None or github_repo:
            raise ValueError(
                "stored-state token inputs require profile prepared-stored-state"
            )
        return None
    if yoke_token_file is None:
        raise ValueError("prepared-stored-state requires --yoke-token-file")
    resolved_yoke_token = yoke_token_file.expanduser()
    if not resolved_yoke_token.is_file():
        raise ValueError(f"yoke token file not found: {resolved_yoke_token}")
    resolved_github_token = github_token_file.expanduser() if github_token_file else None
    if resolved_github_token is not None and not resolved_github_token.is_file():
        raise ValueError(f"github credential file not found: {resolved_github_token}")
    if github_repo and resolved_github_token is None:
        raise ValueError("--github-repo requires --github-token-file")
    return StoredStateProfile(
        yoke_token_file=resolved_yoke_token,
        github_token_file=resolved_github_token,
        github_repo=github_repo,
    )


def _stored_state_profile_for_reset(
    profile: str,
    *,
    host: Mapping[str, object],
    endpoint: str,
    yoke_token_file: Path | None,
    github_token_file: Path | None,
    github_repo: str | None,
) -> StoredStateProfile | None:
    if profile != "prepared-stored-state":
        return _stored_state_profile(
            profile,
            yoke_token_file=yoke_token_file,
            github_token_file=github_token_file,
            github_repo=github_repo,
        )
    raw_stored_state = host.get("stored_state")
    stored_state = raw_stored_state if isinstance(raw_stored_state, Mapping) else {}
    wants_github = bool(stored_state.get("github_connection")) or (
        github_token_file is not None
    )
    resolved_yoke_token = yoke_token_file or _default_yoke_token_file(endpoint)
    resolved_github_token = github_token_file
    if resolved_github_token is None and wants_github:
        resolved_github_token = LOCAL_GITHUB_TOKEN_PATH
    resolved_github_repo = github_repo or str(stored_state.get("github_repo") or "")
    return _stored_state_profile(
        profile,
        yoke_token_file=resolved_yoke_token,
        github_token_file=resolved_github_token,
        github_repo=resolved_github_repo or None,
    )


def _default_yoke_token_file(endpoint: str) -> Path:
    return LOCAL_TOKEN_STAGING_ROOT / f"yoke-{_safe_slug(endpoint)}.token"


def _host_metadata(
    profile: str,
    *,
    stored_state: StoredStateProfile | None,
) -> dict[str, object]:
    if profile == "prepared-screen-term":
        return {"terminal_profile": "screen-256color"}
    if profile == "prepared-stored-state" and stored_state is not None:
        stored_state_metadata: dict[str, object] = {
            "yoke_connection": True,
            "github_connection": stored_state.github_token_file is not None,
        }
        if stored_state.github_repo:
            stored_state_metadata["github_repo"] = stored_state.github_repo
        return {"stored_state": stored_state_metadata}
    if profile == "prepared-no-git":
        return {"package_install": {"git": "missing", "sudo": "available"}}
    if profile == "prepared-no-git-no-sudo":
        return {"package_install": {"git": "missing", "sudo": "missing"}}
    if profile == "fault-injection":
        return {"fault_injection": True}
    return {}


def _stored_state_profile_command(
    *,
    base_url: str,
    endpoint: str,
    has_github_token: bool,
    github_repo: str | None,
) -> str:
    yoke_bin = "\"$HOME/.local/bin/yoke\""
    config_path = "\"$HOME/.yoke/config.json\""
    endpoint_arg = shlex.quote(endpoint)
    base_url_arg = shlex.quote(base_url)
    parts = [
        "set -eu",
        f"chmod 600 {REMOTE_YOKE_TOKEN_PATH}",
        (
            f"{yoke_bin} connection set {endpoint_arg} --transport https "
            f"--api-url {base_url_arg} --token-file {REMOTE_YOKE_TOKEN_PATH} "
            f"--non-prod --config {config_path} >/tmp/yoke-stored-state-env.json"
        ),
        f"{yoke_bin} env use {endpoint_arg} --config {config_path} >/tmp/yoke-stored-state-active-env.json",
        f"rm -f {REMOTE_YOKE_TOKEN_PATH}",
        "test -s \"$HOME/.yoke/config.json\"",
        f"test -f \"$HOME/.yoke/secrets/{endpoint}.token\"",
    ]
    if has_github_token:
        github_repo_arg = (
            f" --github-repo {shlex.quote(github_repo)}" if github_repo else ""
        )
        parts.extend(
            [
                f"chmod 600 {REMOTE_GITHUB_TOKEN_PATH}",
                (
                    f"{yoke_bin} github connect --token-file "
                    f"{REMOTE_GITHUB_TOKEN_PATH}{github_repo_arg} "
                    f"--config {config_path} --json "
                    ">/tmp/yoke-stored-state-github.json"
                ),
                f"rm -f {REMOTE_GITHUB_TOKEN_PATH}",
                "test -f \"$HOME/.yoke/secrets/github.token\"",
            ]
        )
    return "; ".join(parts)


def _path_broken_profile_command() -> str:
    return (
        "rm -f "
        "\"$HOME/.zprofile\" "
        "\"$HOME/.zshenv\" "
        "\"$HOME/.zshrc\" "
        "\"$HOME/.bash_profile\" "
        "\"$HOME/.bash_login\" "
        "\"$HOME/.bashrc\" "
        "\"$HOME/.profile\"; "
        "test -x \"$HOME/.local/bin/yoke\"; "
        "test -x \"$HOME/.local/bin/uv\"; "
        "test -x \"$HOME/.local/bin/uvx\""
    )


def _no_git_profile_command(distro: str) -> str:
    if distro == "ubuntu-24.04":
        remove = "sudo apt-get remove -y git >/dev/null 2>&1 || true"
    else:
        remove = (
            "sudo dnf remove -y git git-core git-core-doc >/dev/null 2>&1 || true"
        )
    return (
        f"{remove}; "
        "hash -r 2>/dev/null || true; "
        "! command -v git >/dev/null 2>&1; "
        "command -v sudo >/dev/null 2>&1"
    )


def _no_git_no_sudo_profile_command() -> str:
    return (
        "git_path=\"$(command -v git || true)\"; "
        "sudo_path=\"$(command -v sudo || true)\"; "
        "if [ -n \"$git_path\" ]; then sudo mv \"$git_path\" \"$git_path.yoke-hidden\"; fi; "
        "if [ -n \"$sudo_path\" ]; then sudo mv \"$sudo_path\" \"$sudo_path.yoke-hidden\"; fi; "
        "hash -r 2>/dev/null || true; "
        "[ -z \"$git_path\" ] || [ ! -e \"$git_path\" ]; "
        "[ -z \"$sudo_path\" ] || [ ! -e \"$sudo_path\" ]; "
        "! command -v git >/dev/null 2>&1; "
        "! command -v sudo >/dev/null 2>&1"
    )


def _disable_curl_command() -> str:
    return (
        "curl_path=\"$(command -v curl || true)\"; "
        "if [ -n \"$curl_path\" ]; then sudo mv \"$curl_path\" \"$curl_path.yoke-hidden\"; fi; "
        "! command -v curl >/dev/null 2>&1"
    )


def _wait_for_ssh(
    runner: CommandRunner,
    key_path: Path,
    public_ip: str,
    *,
    ssh_user: str,
) -> None:
    last_error = ""
    for _attempt in range(30):
        result = runner.run(
            ssh_argv(key_path, public_ip, "true", ssh_user=ssh_user),
            timeout=15,
        )
        if result.returncode == 0:
            return
        last_error = (result.stderr or result.stdout).strip()
        time.sleep(8)
    raise RuntimeError(f"SSH did not become ready for {public_ip}: {last_error}")


def _run_ssh(
    runner: CommandRunner,
    key_path: Path,
    public_ip: str,
    command: str,
    *,
    ssh_user: str = DEFAULT_SSH_USER,
    timeout: int,
) -> None:
    result = runner.run(
        ssh_argv(key_path, public_ip, command, ssh_user=ssh_user),
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = _combined_output_tail(result)
        raise RuntimeError(
            f"remote command failed for {public_ip} rc={result.returncode}: {detail}"
        )


def _load_ledger(ledger_path: Path) -> dict[str, object]:
    ledger = json_helper.load_path(ledger_path)
    if not isinstance(ledger, dict):
        raise ValueError(f"ledger root must be a JSON object: {ledger_path}")
    return ledger


def _select_ledger_host(
    ledger: Mapping[str, object],
    host_id: str | None,
) -> dict[str, object]:
    hosts = [host for host in ledger.get("hosts", []) if isinstance(host, dict)]
    if not hosts:
        raise ValueError("ledger has no hosts")
    if host_id is None:
        return hosts[0]
    for host in hosts:
        if str(host.get("host_id") or "") == host_id:
            return host
    raise ValueError(f"ledger has no host_id: {host_id}")


def ssh_argv(
    key_path: Path,
    public_ip: str,
    command: str,
    *,
    ssh_user: str = DEFAULT_SSH_USER,
) -> list[str]:
    return [
        "ssh",
        "-i",
        str(key_path),
        *[part for option in SSH_OPTIONS for part in ("-o", option)],
        f"{ssh_user}@{public_ip}",
        command,
    ]


def scp_argv(
    key_path: Path,
    public_ip: str,
    local_path: Path,
    remote_path: str,
    *,
    ssh_user: str = DEFAULT_SSH_USER,
) -> list[str]:
    return [
        "scp",
        "-i",
        str(key_path),
        *[part for option in SSH_OPTIONS for part in ("-o", option)],
        str(local_path),
        f"{ssh_user}@{public_ip}:{remote_path}",
    ]


def _copy_file_to_remote(
    runner: CommandRunner,
    key_path: Path,
    public_ip: str,
    local_path: Path,
    remote_path: str,
    *,
    ssh_user: str,
) -> None:
    result = runner.run(
        scp_argv(
            key_path,
            public_ip,
            local_path,
            remote_path,
            ssh_user=ssh_user,
        )
    )
    if result.returncode != 0:
        detail = _combined_output_tail(result)
        raise RuntimeError(f"scp to {remote_path} failed rc={result.returncode}: {detail}")


def _cleanup_created(
    runner: CommandRunner,
    env: Mapping[str, str],
    created: Mapping[str, object],
) -> None:
    instance_ids = [str(value) for value in created.get("instance_ids", [])]
    if instance_ids:
        _aws_best_effort(
            runner, env, ["ec2", "terminate-instances", "--instance-ids", *instance_ids]
        )
        _aws_best_effort(
            runner,
            env,
            ["ec2", "wait", "instance-terminated", "--instance-ids", *instance_ids],
        )
    sg_id = str(created.get("security_group_id") or "")
    if sg_id:
        _aws_best_effort(
            runner, env, ["ec2", "delete-security-group", "--group-id", sg_id]
        )
    key_name = str(created.get("key_name") or "")
    if key_name:
        _aws_best_effort(
            runner, env, ["ec2", "delete-key-pair", "--key-name", key_name]
        )
    key_path = Path(str(created.get("key_path") or "")).expanduser()
    if key_path.is_file():
        key_path.unlink()


def _aws_text(
    runner: CommandRunner,
    env: Mapping[str, str],
    args: Sequence[str],
    *,
    secret_stdout: bool = False,
) -> str:
    result = runner.run(["aws", *args], env=env)
    if result.returncode != 0:
        detail = (result.stderr or ("" if secret_stdout else result.stdout)).strip()
        raise RuntimeError(
            f"aws {' '.join(args[:3])} failed rc={result.returncode}: {detail}"
        )
    return result.stdout.strip()


def _aws_best_effort(
    runner: CommandRunner,
    env: Mapping[str, str],
    args: Sequence[str],
) -> None:
    runner.run(["aws", *args], env=env)


def _combined_output_tail(result: CommandResult, limit: int = 2000) -> str:
    parts = [part.strip() for part in (result.stderr, result.stdout) if part.strip()]
    return "\n".join(parts)[-limit:]


def _write_private_key(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _tag_spec(resource_type: str, campaign_id: str, expires_at: object) -> str:
    tags = [
        f"{{Key=Purpose,Value={PURPOSE_TAG}}}",
        f"{{Key=Campaign,Value={campaign_id}}}",
        f"{{Key=ExpiresAt,Value={expires_at}}}",
    ]
    return f"ResourceType={resource_type},Tags=[{','.join(tags)}]"


def _validate_campaign_id(campaign_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,80}", campaign_id):
        raise ValueError(
            "campaign_id must be 3-81 chars of letters, numbers, dot, underscore, or dash"
        )


def _validate_count(count: int) -> None:
    if count < 1 or count > DEFAULT_MAX_COUNT:
        raise ValueError(f"count must be between 1 and {DEFAULT_MAX_COUNT}")


def _validate_profile(profile: str) -> None:
    if profile not in SUPPORTED_PROFILES:
        raise ValueError(f"unsupported profile: {profile}")


def _validate_reset_profile(profile: str) -> None:
    if profile not in RESETTABLE_PROFILES:
        raise ValueError(f"unsupported reset profile: {profile}")


def _reset_command(profile: str) -> str:
    _validate_reset_profile(profile)
    return (
        "pkill -TERM -u \"$(id -u)\" -f '[y]oke.*onboard' >/dev/null 2>&1 || true; "
        "sleep 1; "
        "pkill -KILL -u \"$(id -u)\" -f '[y]oke.*onboard' >/dev/null 2>&1 || true; "
        "tmux kill-server >/dev/null 2>&1 || true; "
        "rm -rf \"$HOME/.yoke\" "
        "\"$HOME/.local/share/uv\" "
        "\"$HOME/.cache/uv\" "
        "\"$HOME/.config/uv\"; "
        "rm -f \"$HOME/.local/bin/yoke\" "
        "\"$HOME/.local/bin/uv\" "
        "\"$HOME/.local/bin/uvx\" "
        "\"/tmp/yoke-install\" "
        "\"/tmp/yoke-stored-stage-token.backup\"; "
        "mkdir -p \"$HOME/.local/bin\""
    )


def _record_reset_profile(
    *,
    ledger_path: Path,
    ledger: dict[str, object],
    host: dict[str, object],
    target_profile: str,
    endpoint: str,
    stored_state: StoredStateProfile | None,
) -> None:
    for key in HOST_METADATA_KEYS:
        host.pop(key, None)
    host["profile"] = target_profile
    host["endpoint"] = endpoint
    host["lease_state"] = "available"
    host.update(_host_metadata(target_profile, stored_state=stored_state))
    json_helper.dump_path(ledger_path, ledger)


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]+", "-", value).strip("-").lower()[:40]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _emit(
    payload: dict[str, object],
    as_json: bool,
    text: str,
) -> int:
    if as_json:
        print(json_helper.dumps_pretty(payload), end="")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
