"""Docker command vocabulary for the local-core launcher."""

from __future__ import annotations

import socket
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from yoke_cli.local_core import state

DEFAULT_API_PORT = 8765
DEFAULT_POSTGRES_PORT = 55432
LOCAL_IMAGE_REPOSITORY = "yoke-core-local"
LOCAL_BUILD_SHA = "local"
POSTGRES_IMAGE = "postgres:16-alpine"
ENV_NAME = "local-core"
NETWORK = "yoke-local-core"
API_CONTAINER = "yoke-local-core-api"
DB_CONTAINER = "yoke-local-core-postgres"
DB_VOLUME = "yoke-local-core-postgres-data"
LABEL = "com.yoke.local-core=1"
API_PORT_IN_CONTAINER = 8765
DB_NAME = "yoke"
DB_USER = "yoke"


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    guidance: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "guidance": self.guidance,
        }


def settings(
    current: Mapping[str, Any],
    image: str | None,
    api_port: int | None,
    postgres_port: int | None,
) -> dict[str, Any]:
    selected_api = int(api_port or current.get("api_port") or DEFAULT_API_PORT)
    selected_pg = int(
        postgres_port or current.get("postgres_port") or DEFAULT_POSTGRES_PORT
    )
    return {
        "image": image or current.get("image"),
        "api_port": selected_api,
        "postgres_port": selected_pg,
        "api_url": f"http://127.0.0.1:{selected_api}",
    }


def local_image_for_checkout(checkout_path: str) -> str:
    resolved = str(Path(checkout_path).expanduser().resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]
    name = re.sub(r"[^a-z0-9_.-]+", "-", Path(resolved).name.lower()).strip("-")
    suffix = f"{name}-{digest}" if name else digest
    return f"{LOCAL_IMAGE_REPOSITORY}:{suffix}"


def build_plan(checkout_path: str, image: str) -> list[list[str]]:
    return [[
        "docker", "build",
        "--build-arg", f"YOKE_BUILD_SHA={LOCAL_BUILD_SHA}",
        "-t", image,
        str(Path(checkout_path).expanduser().resolve()),
    ]]


def start_plan(
    image: str,
    *,
    env_file: str,
    api_port: int,
    postgres_port: int,
) -> list[list[str]]:
    return [
        ["docker", "network", "create", NETWORK],
        ["docker", "volume", "create", DB_VOLUME],
        ["docker", "rm", "-f", API_CONTAINER, DB_CONTAINER],
        db_run_cmd(env_file, postgres_port),
        *bootstrap_plan(image, env_file),
        *api_plan(image, env_file, api_port),
    ]


def db_run_cmd(env_file: str, postgres_port: int) -> list[str]:
    return [
        "docker", "run", "-d", "--name", DB_CONTAINER, "--label", LABEL,
        "--network", NETWORK, "--env-file", env_file,
        "-p", f"127.0.0.1:{postgres_port}:5432",
        "-v", f"{DB_VOLUME}:/var/lib/postgresql/data", POSTGRES_IMAGE,
    ]


def bootstrap_plan(image: str, env_file: str) -> list[list[str]]:
    return [[
        "docker", "run", "--rm", "--network", NETWORK, "--env-file", env_file,
        image, "python3", "-m", "yoke_core.domain.environment_bootstrap",
    ]]


def api_plan(image: str, env_file: str, api_port: int) -> list[list[str]]:
    return [[
        "docker", "run", "-d", "--name", API_CONTAINER, "--label", LABEL,
        "--network", NETWORK, "--env-file", env_file,
        "-p", f"127.0.0.1:{api_port}:{API_PORT_IN_CONTAINER}",
        image, "python3", "-m", "yoke_core.api.server_entrypoint",
    ]]


def token_plan(image: str, env_file: str) -> list[str]:
    return [
        "docker", "run", "--rm", "--network", NETWORK, "--env-file", env_file,
        image, "python3", "-m", "yoke_core.domain.api_tokens_cli",
        "bootstrap-admin", "--actor-label", "local-core",
        "--project", "yoke", "--name", "local-core-admin",
    ]


def base_payload(
    action: str,
    *,
    image: str | None,
    api_port: int,
    postgres_port: int,
    system: str,
    machine_home: str | None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "action": action,
        "installed": False,
        "running": False,
        "healthy": False,
        "state_dir": str(state.state_dir(machine_home)),
        "api": {"url": f"http://127.0.0.1:{api_port}", "port": api_port},
        "postgres": {"port": postgres_port},
        "image": image,
        "env": ENV_NAME,
        "runtime": {"platform": system, "docker": {}, "colima": {}},
        "issues": [],
    }


def issue(code: str, message: str, guidance: str) -> Issue:
    return Issue(code=code, message=message, guidance=guidance)


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", int(port)))
        except OSError:
            return False
    return True


def redact(args: Sequence[str]) -> list[str]:
    return ["<env-file>" if "local-core.env" in str(arg) else str(arg) for arg in args]


def planned_payload(
    base: dict[str, Any],
    plan: Sequence[Sequence[str]],
    dry_run: bool,
    issues: Sequence[Issue],
    results: Sequence[Any] = (),
    *,
    ok: bool = False,
) -> dict[str, Any]:
    base.update({
        "ok": (ok or dry_run) and not issues,
        "dry_run": dry_run,
        "plan": [redact(cmd) for cmd in plan],
        "issues": [issue.as_dict() for issue in issues],
    })
    if results:
        base["commands"] = [
            {"args": redact(r.args), "returncode": r.returncode}
            for r in results
        ]
    return base


__all__ = [
    "API_CONTAINER",
    "DB_CONTAINER",
    "DB_NAME",
    "DB_USER",
    "DB_VOLUME",
    "DEFAULT_API_PORT",
    "DEFAULT_POSTGRES_PORT",
    "ENV_NAME",
    "Issue",
    "LOCAL_IMAGE_REPOSITORY",
    "NETWORK",
    "api_plan",
    "base_payload",
    "build_plan",
    "bootstrap_plan",
    "issue",
    "local_image_for_checkout",
    "planned_payload",
    "port_free",
    "redact",
    "settings",
    "start_plan",
    "token_plan",
]
